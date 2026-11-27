#!/usr/bin/env python3
"""Explicit local Docker Python adapter. It does not connect to any model API."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

DEFAULT_CONTEXT = "colima-harbor-parity"
DEFAULT_IMAGE = "zerobench/tools:20261126-v1"
DEFAULT_ROOT = Path.home() / ".local/share/zerobench-runtime/trials"
OWNER = "zerobench-local-runtime-v1"
LABEL = "io.zerobench.local-runtime"
PROXIES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy", "FTP_PROXY", "ftp_proxy")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}


class RuntimeErrorBase(RuntimeError):
    pass


class CleanupFailed(RuntimeErrorBase):
    """Container shutdown could not be confirmed; the harness must stop this trial."""


def now():
    return datetime.now(timezone.utc).isoformat()


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("Caller budget exhausted")
    return value


def deadline_for(seconds):
    if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("remaining_seconds must be a finite positive number")
    return time.monotonic() + seconds


def json_read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_write(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def local_path(path, must_exist=False):
    """Reject /Volumes, symlink redirects there, and another device than local home."""
    supplied = Path(path).expanduser().absolute()
    resolved = supplied.resolve(strict=must_exist)
    for candidate in (supplied, resolved):
        if candidate == Path("/Volumes") or Path("/Volumes") in candidate.parents:
            raise RuntimeErrorBase(f"External-volume paths are not allowed: {candidate}")
    ancestor = resolved
    while not ancestor.exists():
        if ancestor == ancestor.parent:
            raise RuntimeErrorBase("Cannot identify local filesystem")
        ancestor = ancestor.parent
    if ancestor.stat().st_dev != Path.home().resolve().stat().st_dev:
        raise RuntimeErrorBase(f"Path is not on the local home filesystem: {resolved}")
    return resolved


def client_environment():
    # Do not forward API keys, DOCKER_HOST, DOCKER_CONTEXT or shell proxy variables.
    return {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL") if k in os.environ}


class LocalDockerRuntime:
    """One managed container per logical trial; only files persist across Python calls."""

    def __init__(self, *, context=DEFAULT_CONTEXT, image=DEFAULT_IMAGE, root=DEFAULT_ROOT,
                 cpus=1.0, memory="1g", pids_limit=128, output_chars=24000, log_bytes=1048576):
        if not (context == "colima" or re.fullmatch(r"colima-[a-zA-Z0-9][a-zA-Z0-9_.-]*", context)):
            raise RuntimeErrorBase("Only an explicitly named local Colima context is supported; Docker Desktop is not allowed")
        if not isinstance(cpus, (int, float)) or not math.isfinite(cpus) or cpus <= 0:
            raise ValueError("cpus must be finite and positive")
        if not re.fullmatch(r"[1-9]\d*(?:[kKmMgG])?", memory):
            raise ValueError("memory must be a Docker size such as 1g or 512m")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./:_-]*", image):
            raise ValueError("Invalid local image tag")
        if pids_limit < 16 or output_chars < 1 or log_bytes < output_chars:
            raise ValueError("Invalid PID/output limits")
        self.context, self.image = context, image
        self.root = local_path(root)
        self.cpus, self.memory, self.pids_limit = float(cpus), memory, int(pids_limit)
        self.output_chars, self.log_bytes = int(output_chars), int(log_bytes)
        self.docker = shutil.which("docker")
        if not self.docker:
            raise RuntimeErrorBase("docker CLI is unavailable; no environment is installed automatically")

    def _command(self, args):
        return [self.docker, "--context", self.context, *args]

    def _docker(self, args, deadline, check=True):
        result = subprocess.run(self._command(args), env=client_environment(), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=remaining(deadline))
        if check and result.returncode:
            raise RuntimeErrorBase("Docker command failed: " + result.stderr[-1200:].strip())
        return result

    def _local_context(self, deadline):
        profile = self.context[len("colima-"):] if self.context.startswith("colima-") else "default"
        expected_socket = local_path(Path.home() / ".colima" / profile / "docker.sock", True)
        if not stat.S_ISSOCK(expected_socket.stat().st_mode):
            raise RuntimeErrorBase("Expected Colima Unix socket is not a socket")
        disk_name = self.context if self.context.startswith("colima-") else "colima"
        disk = local_path(Path.home() / ".colima/_lima/_disks" / disk_name / "datadisk", True)
        if not disk.is_file():
            raise RuntimeErrorBase("Expected Colima data disk is not a regular local file")
        result = self._docker(["context", "inspect", self.context], deadline)
        contexts = json.loads(result.stdout)
        host = contexts[0].get("Endpoints", {}).get("docker", {}).get("Host", "")
        if not host.startswith("unix://") or local_path(host[7:], True) != expected_socket:
            raise RuntimeErrorBase("Docker context endpoint does not match this local Colima profile")
        info = disk.stat()
        return {"context": self.context, "endpoint": host, "resolved_socket": str(expected_socket),
                "resolved_datadisk": str(disk), "disk_logical_bytes": info.st_size,
                "disk_allocated_bytes": getattr(info, "st_blocks", 0) * 512,
                "same_filesystem_as_local_home": True, "external_volumes_rejected": True}

    def _root(self, create=False):
        root = local_path(self.root)
        marker = root / ".zerobench-runtime-root.json"
        if root.exists():
            if not root.is_dir():
                raise RuntimeErrorBase("Runtime root is not a directory")
            if marker.exists():
                info = json_read(marker)
                if info.get("owner") != OWNER or info.get("root") != str(root):
                    raise RuntimeErrorBase("Runtime root marker does not match this adapter/path")
                return root
            if any(root.iterdir()):
                raise RuntimeErrorBase("Refusing an existing nonempty directory without this adapter's root marker")
        if not create:
            raise RuntimeErrorBase("Managed runtime root does not exist")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with marker.open("x", encoding="utf-8") as stream:
                json.dump({"owner": OWNER, "root": str(root), "created_at": now()}, stream)
        except FileExistsError:
            info = json_read(marker)
            if info.get("owner") != OWNER or info.get("root") != str(root):
                raise RuntimeErrorBase("Concurrent root initialization has an incompatible marker")
        marker.chmod(0o600)
        return root

    def _trial(self, trial_id):
        if not isinstance(trial_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", trial_id) or ".." in trial_id:
            raise ValueError("trial_id must be a short safe identifier without path components")
        return local_path(self.root / trial_id)

    def _metadata(self, trial_id):
        self._root()
        directory = self._trial(trial_id)
        info = json_read(directory / "runtime.json")
        if info.get("owner") != OWNER or info.get("trial_id") != trial_id or info.get("context") != self.context:
            raise RuntimeErrorBase("Trial metadata ownership/context mismatch")
        if info.get("trial_directory") != str(directory) or info.get("workdir") != str(directory / "work"):
            raise RuntimeErrorBase("Trial paths do not match their managed directory")
        local_path(info["workdir"], True)
        return directory, info

    def _state(self, directory, **changes):
        path = directory / "runtime.json"
        info = json_read(path)
        info.update(changes)
        info["updated_at"] = now()
        json_write(path, info)

    def _inspect_owned(self, info, deadline, allow_missing=False):
        ref = info.get("container_id") or info["container_name"]
        result = self._docker(["container", "inspect", ref], deadline, check=False)
        if result.returncode:
            if allow_missing and re.search(r"No such (?:object|container)", result.stderr, re.I):
                return None
            raise RuntimeErrorBase("Cannot inspect the managed container: " + result.stderr[-800:].strip())
        container = json.loads(result.stdout)[0]
        labels = container.get("Config", {}).get("Labels") or {}
        if labels.get(LABEL) != OWNER or labels.get(LABEL + ".trial") != info["trial_id"] or labels.get(LABEL + ".token") != info["ownership_token"]:
            raise RuntimeErrorBase("Container labels do not match this trial; refusing to use or remove it")
        return container

    @staticmethod
    def _assert_mounts(container, info):
        actual = {(m.get("Destination"), m.get("Source"), m.get("RW"), m.get("Type")) for m in container.get("Mounts", [])}
        expected = {("/workspace", info["workdir"], True, "bind"),
                    ("/workspace/image.png", str(Path(info["workdir"]) / "image.png"), False, "bind")}
        # /tmp is an explicit ephemeral tmpfs, not a host mount.
        binds = {row for row in actual if row[3] == "bind"}
        if binds != expected or any(row[3] not in {"bind", "tmpfs"} for row in actual):
            raise RuntimeErrorBase("Container host mounts differ from the two allowed trial mounts")
        host = container.get("HostConfig", {})
        if host.get("Privileged") or not host.get("ReadonlyRootfs") or host.get("NetworkMode") != "bridge":
            raise RuntimeErrorBase("Container isolation does not match the requested runtime")
        values = dict(item.split("=", 1) for item in container.get("Config", {}).get("Env", []) if "=" in item)
        if any(values.get(name) for name in PROXIES):
            raise RuntimeErrorBase("Docker client injected a nonempty proxy; direct networking was not established")
        secret_names = [key for key, value in values.items() if value and re.search(r"API_KEY|ACCESS_TOKEN|AUTHORIZATION|PASSWORD|SECRET|BEARER", key, re.I)]
        if secret_names:
            raise RuntimeErrorBase("Unexpected credential-like environment names in image/container: " + ", ".join(secret_names))

    def start(self, trial_id, public_image, *, remaining_seconds=60):
        deadline = deadline_for(remaining_seconds)
        context_proof = self._local_context(deadline)
        source = local_path(public_image, True)
        if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
            raise RuntimeErrorBase("public_image must be one existing local image file")
        image_result = self._docker(["image", "inspect", self.image], deadline)
        image = json.loads(image_result.stdout)[0]
        root = self._root(create=True)
        directory = self._trial(trial_id)
        if directory.exists() and any(directory.iterdir()):
            raise RuntimeErrorBase("Trial directory is nonempty. Use exec/status for its existing trial, or choose a new trial ID")
        directory.mkdir(mode=0o700, exist_ok=True)
        workdir = directory / "work"
        workdir.mkdir(mode=0o700)
        (directory / "logs").mkdir(mode=0o700)
        shutil.copyfile(source, workdir / "image.png")
        (workdir / "image.png").chmod(0o444)
        token = uuid.uuid4().hex
        name = "zerobench-" + trial_id.lower().replace("_", "-")[:50] + "-" + token[:10]
        info = {"schema_version": "1.0", "owner": OWNER, "trial_id": trial_id, "ownership_token": token,
                "context": self.context, "context_storage": context_proof, "trial_directory": str(directory),
                "workdir": str(workdir), "public_image": str(workdir / "image.png"),
                "public_image_original_name": source.name, "public_image_bytes": source.stat().st_size,
                "container_name": name, "container_id": None, "state": "creating", "created_at": now(),
                "image_tag": self.image, "image_architecture": image.get("Architecture"), "image_os": image.get("Os"),
                "limits": {"cpus": self.cpus, "memory": self.memory, "memory_swap_total": self.memory, "pids": self.pids_limit,
                           "tmpfs_bytes": 268435456, "uid": os.getuid(), "gid": os.getgid(), "rootfs_read_only": True,
                           "output_chars": self.output_chars, "per_exec_log_bytes": self.log_bytes, "per_trial_tool_exec_concurrency": 1},
                "network": {"mode": "bridge", "public_internet_allowed": True, "proxy_environment": "explicitly empty, including Docker client automatic proxy variables",
                            "public_only_egress_filter": False},
                "mount_policy": "only the trial workdir RW and its image.png file RO; no case, repo, API credentials or Docker socket",
                "python_state": "new process each call; files persist until the user removes trial artifacts",
                "adapter_opt_in": True, "existing_runner_modified": False}
        json_write(directory / "runtime.json", info)
        args = ["create", "--name", name, "--pull=never", "--init", "--cpus", str(self.cpus),
                "--memory", self.memory, "--memory-swap", self.memory, "--pids-limit", str(self.pids_limit),
                "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                "--read-only", "--network=bridge", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
                "--workdir", "/workspace", "--label", f"{LABEL}={OWNER}", "--label", f"{LABEL}.trial={trial_id}",
                "--label", f"{LABEL}.token={token}", "--mount", f"type=bind,source={workdir},target=/workspace",
                "--mount", f"type=bind,source={workdir / 'image.png'},target=/workspace/image.png,readonly",
                "--env", "MPLCONFIGDIR=/tmp/matplotlib", "--env", "XDG_CACHE_HOME=/tmp/cache"]
        for key in PROXIES:
            args += ["--env", f"{key}="]
        args += ["--entrypoint", "/bin/sleep", self.image, "infinity"]
        try:
            created = self._docker(args, deadline)
            info["container_id"] = created.stdout.strip()
            json_write(directory / "runtime.json", info)
            container = self._inspect_owned(info, deadline)
            self._assert_mounts(container, info)
            self._docker(["start", info["container_id"]], deadline)
            environment_code = "import sys,platform,json,importlib.metadata as m;print(json.dumps({'python':sys.version,'platform':platform.platform(),'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))"
            environment = self._docker(["exec", info["container_id"], "python", "-I", "-c", environment_code], deadline)
            self._state(directory, state="running", environment=json.loads(environment.stdout), started_at=now())
            return json_read(directory / "runtime.json")
        except BaseException:
            # A create request may have succeeded even if its client timed out.
            try:
                self._remove_owned(directory, info, reason="start_failed")
            except Exception as cleanup:
                raise CleanupFailed(f"Start failed and cleanup was not confirmed for {name}: {cleanup}") from cleanup
            raise

    def _remove_owned(self, directory, info, *, reason):
        """A timeout is contained only after daemon-side removal/stoppage is confirmed."""
        cleanup_deadline = time.monotonic() + 20
        last_error = None
        for attempt in range(2):
            try:
                container = self._inspect_owned(info, cleanup_deadline, allow_missing=True)
                if container is not None:
                    self._docker(["container", "rm", "--force", container["Id"]], cleanup_deadline)
                    container = self._inspect_owned(info, cleanup_deadline, allow_missing=True)
                if container is None:
                    self._state(directory, state="stopped", stopped_at=now(), stop_reason=reason, daemon_shutdown_confirmed=True)
                    return {"removed": True, "daemon_shutdown_confirmed": True, "artifacts_preserved": str(directory)}
            except (RuntimeErrorBase, TimeoutError, subprocess.TimeoutExpired, ValueError) as exc:
                last_error = exc
        self._state(directory, state="cleanup_failed", stop_reason=reason, daemon_shutdown_confirmed=False)
        raise CleanupFailed(f"Could not confirm shutdown of owned container {info['container_name']}; do not schedule further work in this trial. {type(last_error).__name__}")

    @contextmanager
    def _exec_lock(self, directory):
        with (directory / "exec.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeErrorBase("Another Python call is active in this trial; harness must serialize per-trial tool calls") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def run_python(self, trial_id, code, *, remaining_seconds, timeout_seconds=60):
        """Caller supplies remaining logical-trial time; no fresh trial budget is created."""
        if not isinstance(code, str) or len(code.encode("utf-8")) > 1048576:
            raise ValueError("Python code must be a string of at most 1 MiB")
        if not isinstance(timeout_seconds, (float, int)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        deadline = deadline_for(min(remaining_seconds, timeout_seconds))
        started = time.monotonic()
        directory, info = self._metadata(trial_id)
        if info.get("state") != "running":
            raise RuntimeErrorBase("This trial container is not running; stopped trials require a new trial ID")
        with self._exec_lock(directory):
            call_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]
            log = directory / "logs" / (call_id + ".stdout.txt")
            code_path = directory / "logs" / (call_id + ".py")
            code_path.write_text(code, encoding="utf-8")
            code_path.chmod(0o600)
            process = None
            observed = {"bytes": 0, "saved": 0}
            reader_error = []
            try:
                self._local_context(deadline)
                container = self._inspect_owned(info, deadline)
                self._assert_mounts(container, info)
                if not container.get("State", {}).get("Running"):
                    raise RuntimeErrorBase("Docker reports that this trial is not running")
                wrapper = "import sys;sys.path.insert(0,'/workspace');exec(compile(sys.stdin.read(),'<model-tool>','exec'),{'__name__':'__main__'})"
                command = ["exec", "-i", "--workdir", "/workspace", info["container_id"], "python", "-I", "-B", "-c", wrapper]
                process = subprocess.Popen(self._command(command), env=client_environment(), stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)

                def consume():
                    try:
                        with log.open("wb") as output:
                            while chunk := process.stdout.read(8192):
                                observed["bytes"] += len(chunk)
                                available = self.log_bytes - observed["saved"]
                                if available > 0:
                                    kept = chunk[:available]
                                    output.write(kept)
                                    observed["saved"] += len(kept)
                    except Exception as exc:
                        reader_error.append(type(exc).__name__)

                def feed():
                    try:
                        process.stdin.write(code.encode("utf-8"))
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass

                reader = threading.Thread(target=consume, daemon=True)
                writer = threading.Thread(target=feed, daemon=True)
                reader.start()
                writer.start()
                process.wait(timeout=remaining(deadline))
                reader.join(timeout=min(1.0, max(0.0, deadline - time.monotonic())))
                if reader.is_alive():
                    raise TimeoutError("Tool output did not close within the caller budget")
                result = {"exit_code": process.returncode, "status": "completed" if process.returncode == 0 else "tool_error",
                          "output": log.read_text(encoding="utf-8", errors="replace")[:self.output_chars] if log.exists() else "",
                          "output_bytes": observed["bytes"], "saved_log_bytes": observed["saved"],
                          "output_truncated": observed["bytes"] > self.output_chars or observed["bytes"] > self.log_bytes,
                          "reader_errors": reader_error, "stdout_log": str(log), "code_log": str(code_path),
                          "seconds": round(time.monotonic() - started, 3), "effective_timeout_seconds": min(remaining_seconds, timeout_seconds),
                          "state_scope": "new Python process; persistent trial files"}
            except (TimeoutError, subprocess.TimeoutExpired) as exc:
                cleanup = self._remove_owned(directory, info, reason="tool_or_trial_timeout")
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
                result = {"exit_code": None, "status": "timeout", "error": type(exc).__name__,
                          "output": log.read_text(encoding="utf-8", errors="replace")[:self.output_chars] if log.exists() else "",
                          "seconds": round(time.monotonic() - started, 3), "effective_timeout_seconds": min(remaining_seconds, timeout_seconds),
                          "cleanup": cleanup, "stdout_log": str(log), "code_log": str(code_path)}
            except KeyboardInterrupt:
                self._remove_owned(directory, info, reason="caller_interrupted")
                raise
            finally:
                if process is not None and process.poll() is None:
                    # This never substitutes for daemon-side timeout cleanup above.
                    process.kill()
                    process.wait(timeout=3)
            json_write(directory / "logs" / (call_id + ".json"), result)
            return result

    def stop(self, trial_id, *, remaining_seconds=30):
        deadline = deadline_for(remaining_seconds)
        self._local_context(deadline)
        directory, info = self._metadata(trial_id)
        return self._remove_owned(directory, info, reason="explicit_stop")

    def status(self, trial_id, *, remaining_seconds=15):
        deadline = deadline_for(remaining_seconds)
        proof = self._local_context(deadline)
        directory, info = self._metadata(trial_id)
        container = self._inspect_owned(info, deadline, allow_missing=True)
        if container is not None:
            self._assert_mounts(container, info)
        return {"trial_id": trial_id, "context": self.context, "recorded_state": info.get("state"),
                "actual_container_exists": container is not None,
                "actual_running": bool(container and container.get("State", {}).get("Running")),
                "container_state": container.get("State") if container else None,
                "artifacts": str(directory), "workdir": info["workdir"], "limits": info["limits"],
                "network": info["network"], "context_storage": proof,
                "environment": info.get("environment"), "existing_runner_modified": False}

    def artifact_path(self, trial_id, relative_path):
        """Resolve an output for inspect_image/view_local_image without host path escape."""
        directory, info = self._metadata(trial_id)
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise RuntimeErrorBase("Artifact path must be relative to the trial workdir")
        workdir = Path(info["workdir"]).resolve()
        resolved = (workdir / candidate).resolve(strict=True)
        if not resolved.is_relative_to(workdir) or not resolved.is_file():
            raise RuntimeErrorBase("Artifact must be an existing file inside this trial workdir")
        return resolved


class DockerPythonAdapter:
    """Small bound-trial adapter for an explicitly opted-in harness."""
    def __init__(self, trial_id, **runtime_options):
        self.trial_id = trial_id
        self.runtime = LocalDockerRuntime(**runtime_options)

    def start(self, public_image, *, remaining_seconds=60):
        return self.runtime.start(self.trial_id, public_image, remaining_seconds=remaining_seconds)

    def run_python(self, code, *, remaining_seconds, timeout_seconds=60):
        return self.runtime.run_python(self.trial_id, code, remaining_seconds=remaining_seconds, timeout_seconds=timeout_seconds)

    def artifact_path(self, relative_path):
        return self.runtime.artifact_path(self.trial_id, relative_path)

    def stop(self):
        return self.runtime.stop(self.trial_id)

    def status(self):
        return self.runtime.status(self.trial_id)


def main():
    # CLI termination takes the same owned-container cleanup path as Ctrl-C.
    # Importing this module does not change a harness's signal handlers.
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "exec", "stop", "status"):
        sub = commands.add_parser(command)
        sub.add_argument("--trial", required=True)
        sub.add_argument("--context", default=DEFAULT_CONTEXT)
        sub.add_argument("--root", type=Path, default=DEFAULT_ROOT)
        if command == "start":
            sub.add_argument("--public-image", required=True, type=Path)
            sub.add_argument("--image", default=DEFAULT_IMAGE)
            sub.add_argument("--cpus", type=float, default=1.0)
            sub.add_argument("--memory", default="1g")
            sub.add_argument("--pids-limit", type=int, default=128)
            sub.add_argument("--remaining-seconds", type=float, default=60)
        elif command == "exec":
            source = sub.add_mutually_exclusive_group(required=True)
            source.add_argument("--code-file", type=Path)
            source.add_argument("--stdin", action="store_true")
            sub.add_argument("--remaining-seconds", type=float, required=True)
            sub.add_argument("--timeout", type=float, default=60)
        else:
            sub.add_argument("--remaining-seconds", type=float, default=30)
    args = parser.parse_args()
    try:
        options = {k: getattr(args, k) for k in ("context", "root", "image", "cpus", "memory", "pids_limit") if hasattr(args, k)}
        runtime = LocalDockerRuntime(**options)
        if args.command == "start":
            result = runtime.start(args.trial, args.public_image, remaining_seconds=args.remaining_seconds)
        elif args.command == "exec":
            code = sys.stdin.read() if args.stdin else args.code_file.read_text(encoding="utf-8")
            result = runtime.run_python(args.trial, code, remaining_seconds=args.remaining_seconds, timeout_seconds=args.timeout)
        else:
            result = getattr(runtime, args.command)(args.trial, remaining_seconds=args.remaining_seconds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in {"timeout", "tool_error"} else 1
    except (RuntimeErrorBase, ValueError, OSError, subprocess.TimeoutExpired, TimeoutError) as exc:
        print(json.dumps({"status": "runtime_error", "error_type": type(exc).__name__, "message": str(exc), "model_api_called": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
