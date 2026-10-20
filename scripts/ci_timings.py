# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Record hosted job durations; compare only matching event and change cohorts."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import time

from build_support import api, require, write as write_json


def seconds(start, end):
    return (datetime.fromisoformat(end.replace('Z', '+00:00')) -
            datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds()


def summarize(jobs):
    completed = [job for job in jobs if job.get('started_at') and job.get('completed_at')
                 and job.get('conclusion') != 'skipped']
    require(completed, 'No completed jobs to measure')
    durations = [{key: job[key] for key in ('name', 'conclusion', 'started_at', 'completed_at')}
                 | {'seconds': seconds(job['started_at'], job['completed_at'])} for job in completed]
    return {'job_count': len(durations), 'job_seconds': sum(job['seconds'] for job in durations),
            'execution_span_seconds': seconds(min(j['started_at'] for j in completed),
                                              max(j['completed_at'] for j in completed)),
            'jobs': durations}


def fetch_jobs(repo, run, attempt):
    jobs = []
    page = 1
    while True:
        data = api(f'repos/{repo}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100&page={page}')
        jobs.extend(data['jobs'])
        if len(data['jobs']) < 100:
            return jobs
        page += 1


def measure(repo, run, attempt, scope):
    # A dependent job can start before the Jobs API exposes completion metadata.
    # Refresh the same attempt instead of accepting an empty or partial Python report.
    for retry in range(6):
        selected = fetch_jobs(repo, run, attempt)
        ready = True
        if scope == 'python':
            gates = [job for job in selected if job['name'].endswith(' / Python quality gate')]
            require(len(gates) <= 1, 'Expected one Python gate in this run')
            if gates:
                prefix = gates[0]['name'].removesuffix(' / Python quality gate') + ' / '
                selected = [job for job in selected if job['name'].startswith(prefix)
                            and not job['name'].endswith(' timings')]
            else:
                selected = []
        else:
            # Main/Release collection must also wait for every prerequisite's
            # metadata, excluding the collectors themselves (including nested Full).
            selected = [job for job in selected if not job['name'].endswith(' timings')]
        ready = bool(selected) and all(
            job.get('conclusion') == 'skipped' or
            (job.get('status') == 'completed' and job.get('conclusion') and
             job.get('started_at') and job.get('completed_at')) for job in selected)
        measurable = any(job.get('started_at') and job.get('completed_at') and
                         job.get('conclusion') != 'skipped' for job in selected)
        if ready and measurable:
            return summarize(selected)
        if retry < 5:
            print('Job timing metadata is not ready; retrying the same run attempt in 5 seconds.', flush=True)
            time.sleep(5)
    raise ValueError('Job timing metadata remained incomplete after 6 attempts')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--scope', choices=('python', 'run'), default='run')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        report = {'schema': 1, 'note': baseline['note'],
                  'runs': [{key: value for key, value in run.items() if key != 'jobs'}
                           | summarize(run['jobs']) for run in baseline['runs']]}
    else:
        repo, run, attempt = (os.environ[key] for key in
                              ('GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))
        report = {'schema': 1, 'repository': repo, 'commit': os.environ['GITHUB_SHA'],
                  'event': os.environ['GITHUB_EVENT_NAME'], 'run_id': run, 'run_attempt': attempt,
                  'scope': args.scope,
                  'note': 'Execution span includes scheduling gaps between first start and last finish; excludes initial queue time.',
                  **measure(repo, run, attempt, args.scope)}
    write_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
