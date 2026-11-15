"""campaign_compile for analysis: people are registered, their appearances are not built.

Same arguments as campaign_compile (`--work` is required). The world import then
yields souls, bindings, world profiles and scheduler rows without the hundreds of
GB the campaign's converted people take; the quest stage's person route builds
appearances at build time. The output is marked and is not a package.
"""
import json
from pathlib import Path
import sys

import campaign_compile
import campaign_compile_resume


def main():
    arguments = sys.argv[1:]
    if '--work' not in arguments or '--output' not in arguments:
        sys.exit('campaign_compile_analysis needs --work and --output')
    campaign_compile_resume.PEOPLE = 'register'
    campaign_compile.main()
    output = Path(arguments[arguments.index('--output') + 1])
    (output / 'analysis-only.json').write_text(json.dumps(dict(
        schema=1, people='registered without appearances', package=False), indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
