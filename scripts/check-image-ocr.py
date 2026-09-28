"""Exercise the real macOS OCR binary against a synthetic document screenshot."""
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
response = subprocess.run(
    [str(root / '.runtime/bin/vision-ocr'), str(root / 'rag/tests/fixtures/ocr_sample.png')],
    capture_output=True, text=True, check=True, timeout=60,
)
text = json.loads(response.stdout)['text']
assert '100.00' in text and '125.00' in text and '2025' in text and 'CNY' in text
print('Native image OCR: numeric fixture and units recognized.')
