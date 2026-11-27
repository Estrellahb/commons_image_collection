"""Grade only complete final-answer submissions against the frozen solution."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def flatten(answer):
    assert len(answer) == 6
    assert len(answer[0]) == 4 and all(len(row) == 3 for row in answer[0])
    assert len(answer[1]) == 3
    fields = {}
    for col, values in zip('ABCD', answer[0]):
        for label, value in zip(['n', 'F', 'H'], values):
            fields[f'Q1.{col}.{label}'] = value
    for label, value in zip(['AB', 'BC', 'CD'], answer[1]):
        fields[f'Q2.{label}'] = value
    fields['Q3.routes'] = answer[2]
    fields['Q4.plans'] = answer[3]
    for question, values in zip([5, 6], answer[4:]):
        assert len(values) == 4 and len(values[3]) == 8
        for label, value in zip(['max_cost', 'sum_cost', 'ties', 'representative'], values):
            fields[f'Q{question}.{label}'] = value
    assert len(fields) == 25
    return fields


for line in (HERE / 'frozen.sha256').read_text().splitlines():
    expected_hash, name = line.split('  ')
    assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == expected_hash
expected = flatten(json.loads((HERE / 'recompute.json').read_text())['baseline']['answer'])
submissions = json.loads((HERE / 'blind_submissions.json').read_text())
assert len(submissions) == 3
records = []
counts = {'correct': 0, 'incorrect': 0, 'timeout': 0, 'infra_error': 0, 'partial': 0}
invalid = json.loads((HERE / 'blind_invalid_attempts.json').read_text())
for trial in invalid:
    counts[trial['status']] += 1
for trial in submissions:
    fields = flatten(trial['answer'])
    grading = [{'field': label, 'expected': expected[label], 'actual': value,
                'correct': expected[label] == value} for label, value in fields.items()]
    wrong = [g['field'] for g in grading if not g['correct']]
    counts['incorrect' if wrong else 'correct'] += 1
    records.append({**trial, 'valid': True, 'whole_correct': not wrong,
                    'correct_fields': sum(g['correct'] for g in grading),
                    'wrong_fields': wrong, 'grading': grading})
all_correct = counts['correct'] == 3
difficulty = ('三次有效试答全部正确，最终按中等难度登记。有效样本中的错答数为零。'
              if all_correct else '本地独立试答出现完整可判分错答，字段及图证归因见内部记录。')
out = {'frozen_version': HERE.name,
       'evaluation': {'tools_enabled': True, 'frozen_version': HERE.name, 'counts': counts,
                      'trajectory': 'blind_trials/trial1.md; blind_trials/trial3.md; blind_trials/trial4.md; blind_invalid_attempts.json',
                      'gt_review': 'recompute.json; independent_verification.json; qa_notes.md',
                      'failure_attribution': '三次全部正确，无实际错答归因' if all_correct else '逐轮见trials'},
       'difficulty_decision': difficulty, 'difficulty_label': '中等' if all_correct else '困难',
       'model_settings': {'model': 'inherited session model', 'model_override': None,
                          'reasoning_override': None, 'fork_turns': 'none', 'tools_enabled': True},
       'invalid_attempts': invalid, 'trials': records}
(HERE / 'blind_trials.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(json.dumps({'counts': counts, 'grading': [(t['id'], t['correct_fields'], t['wrong_fields']) for t in records]}, ensure_ascii=False))
