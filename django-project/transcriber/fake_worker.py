import argparse
import json
import sys
import zipfile
from pathlib import Path

from batch_runner import STANDARD_FORMATS, MERGED_FORMATS


def main():
    parser = argparse.ArgumentParser(description='Fake transcription worker for integration tests only.')
    parser.add_argument('--input_dir', required=True)
    parser.add_argument('-o', required=True)
    parser.add_argument('-m', required=True)
    parser.add_argument('--language', default='auto')
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--job_name')
    parser.add_argument('--merge_speakers', action='store_true')
    parser.add_argument('--transcriber_gui', action='store_true')
    parser.add_argument('--test-outcome', choices=['success', 'fail', 'missing', 'malformed'], default='success')
    args = parser.parse_args()
    if args.test_outcome == 'fail':
        print('Deliberate fake-worker failure', file=sys.stderr)
        return 2
    output = Path(args.o)
    output.mkdir(parents=True, exist_ok=True)
    for source in sorted(Path(args.input_dir).iterdir()):
        if args.test_outcome == 'missing':
            continue
        transcript = {'lines': [
            {'startTime': '00:00:00.000', 'endTime': '00:00:01.000',
             'speakerDesignation': 'Speaker 1', 'text': 'Synthetic test transcript. No speech recognition was performed.'},
        ], 'test_worker': True}
        if args.test_outcome == 'malformed':
            transcript = {'invalid': True}
        language = args.language if args.language != 'auto' else 'en'
        basename = f'{source.stem}_{args.m}' + ('' if args.m == 'parakeet' else f'_{language}')
        for suffix, formats in [('', STANDARD_FORMATS), ('_merged', MERGED_FORMATS)]:
            for extension in formats:
                content = json.dumps(transcript) if extension == 'dote.json' else 'Synthetic test output only.'
                (output / f'{basename}{suffix}.{extension}').write_text(content, encoding='utf-8')
    (output / 'transcribe.log').write_text('Synthetic worker log.\n', encoding='utf-8')
    with zipfile.ZipFile(output / f'{args.job_name}.zip', 'w') as archive:
        for artifact in sorted(output.iterdir()):
            if artifact.suffix not in ('.zip', '.log'):
                archive.write(artifact, artifact.name)
    print('Fake worker finished; outputs contain synthetic text only.')
    return 0


if __name__ == '__main__':
    sys.exit(main())