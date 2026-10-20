# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Consume Core #637 schema-2 assets with producer and source authentication."""

from pathlib import Path, PurePosixPath
import hashlib
import platform
import re
import tarfile
import zipfile

from build_support import ROOT, api, digest, read, require, run, write

REPOSITORY = 'OpenTLV/opentlv'
SIGNER = REPOSITORY + '/.github/workflows/core-release.yml'
REQUIRED_FEATURES = tuple(read(ROOT / 'cmake/core-features.json'))
# Core schema-2 Full evidence contract, shared with the release producer.
FULL_CHECKS = frozenset(('clang', 'static', 'consumers', 'codeql', 'msvc', 'gcc',
                         'properties', 'query', 'fuzz', 'capabilities', 'abi', 'memcheck'))
CONFIGURATION_SOURCES = frozenset((
    'CMakeLists.txt', 'cmake/compiler.cmake', 'cmake/capability_options.cmake',
    'cmake/format_options.cmake', 'scripts/check_cmake_integration.py',
    'scripts/check_capabilities.py', 'scripts/abi/check.py'))
WORKFLOWS = frozenset((
    'build-clang.yml', 'build-msvc.yml', 'static-analysis.yml', 'cmake-consumers.yml',
    'codeql.yml', 'build-gcc.yml', 'property.yml', 'query-hardening.yml', 'fuzz.yml',
    'capabilities.yml', 'abi.yml', 'valgrind.yml', 'core-full.yml',
    'core-checks.yml', 'core-release.yml'))


def lock(require_release=False):
    value = read(ROOT / 'cmake/core-artifact.json')
    require(value.get('schema') == 1 and value.get('repository') == REPOSITORY,
            'Unsupported Core artifact lock')
    require(isinstance(value.get('commit'), str) and
            re.fullmatch('[0-9a-f]{40}', value['commit']), 'Expected an exact Core commit')
    require(isinstance(value.get('version'), str) and
            re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', value['version']),
            'Expected an exact Core version')
    require(type(value.get('allow_verified_source')) is bool, 'Explicit fallback policy required')
    tag = value.get('release_tag')
    require(tag is None or (isinstance(tag, str) and re.fullmatch(r'v\d+\.\d+\.\d+(?:-[\w.-]+)?', tag)),
            'Invalid Core release tag')
    require(tag is None or tag == 'v' + value['version'], 'Core version/tag mismatch')
    if require_release:
        require(tag is not None, 'A published Core schema-2 release must be locked for verified-release builds')
    return value


def safe_name(name):
    require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name),
            'Unsafe artifact filename')
    return name


def extract(archive, destination):
    """Extract regular files and contained relative tar links; reject traversal and devices."""
    destination.mkdir(parents=True, exist_ok=False)

    def target(name):
        require('\\' not in name and ':' not in name and '\0' not in name, 'Unsafe archive path')
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts, 'Archive traversal')
        result = destination.joinpath(*path.parts)
        require(result.resolve().is_relative_to(destination.resolve()), 'Archive escapes destination')
        return result

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                # ZipInfo normalizes backslashes on Windows; inspect the original.
                path = target(member.orig_filename)
                require((member.external_attr >> 16) & 0o170000 != 0o120000, 'ZIP symlink is unsupported')
                if member.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    require(not path.exists(), 'Duplicate archive file')
                    path.write_bytes(source.read(member))
    else:
        with tarfile.open(archive) as source:
            links = []
            for member in source:
                path = target(member.name)
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    require(not path.exists(), 'Duplicate archive file')
                    with source.extractfile(member) as stream:
                        path.write_bytes(stream.read())
                    path.chmod(member.mode & 0o777)
                elif member.issym():
                    require('\\' not in member.linkname and ':' not in member.linkname and
                            not PurePosixPath(member.linkname).is_absolute(), 'Unsafe symlink')
                    link = (path.parent / member.linkname).resolve()
                    require(link.is_relative_to(destination.resolve()), 'Symlink traversal')
                    links.append((path, member.linkname))
                else:
                    raise ValueError('Unsupported archive member')
            for path, link in links:
                path.parent.mkdir(parents=True, exist_ok=True)
                require(not path.exists() and not path.is_symlink(), 'Duplicate symlink')
                path.symlink_to(link)


def checksums(path):
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        require(match is not None, 'Malformed SHA256SUMS')
        name = safe_name(match[2])
        require(name not in result, 'Duplicate checksum')
        result[name] = match[1]
    return result


def verify_manifest(manifest, selected):
    require(manifest.get('schema') == 2 and manifest.get('commit') == selected['commit'] and
            manifest.get('version') == selected['release_tag'][1:], 'Wrong Core manifest identity/schema')
    quality = manifest.get('quality', {})
    candidate = manifest.get('candidate', {})
    require(quality.get('schema') == 2 and quality.get('tier') == 'full' and
            quality.get('repository') == REPOSITORY and quality.get('commit') == selected['commit'],
            'Core Full CI identity missing')
    require(candidate.get('version') == selected['version'] and
            candidate.get('commit') == selected['commit'] and candidate.get('tag') == selected['release_tag'] and
            candidate.get('repository') == REPOSITORY and candidate.get('run_id') == quality.get('run_id') and
            candidate.get('run_attempt') == quality.get('run_attempt'), 'Core candidate evidence mismatch')
    require(quality.get('run_id') and quality.get('run_attempt') and
            isinstance(quality.get('checks'), dict) and set(quality['checks']) == FULL_CHECKS and
            all(v == 'success' for v in quality['checks'].values()),
            'Core Full CI did not pass')
    configuration = quality.get('configuration', {})
    require(configuration.get('inputs') == {'full': True, 'release_tag': selected['release_tag']} and
            set(configuration.get('configuration_sources', {})) == CONFIGURATION_SOURCES and
            set(configuration.get('workflows', {})) == WORKFLOWS,
            'Core Full configuration is incomplete')
    for record in configuration['workflows'].values():
        require(isinstance(record.get('definition'), str) and
                hashlib.sha256(record['definition'].encode()).hexdigest() == record.get('sha256'),
                'Core workflow definition/hash mismatch')
    names = set()
    for item in manifest.get('artifacts', []):
        name = safe_name(item.get('filename'))
        require(name not in names, 'Duplicate manifest artifact')
        names.add(name)
        require(item.get('commit') == selected['commit'] and item.get('version') == manifest['version'] and
                re.fullmatch('[0-9a-f]{64}', item.get('sha256', '')), 'Invalid Core artifact record')
    require(names, 'Empty Core manifest')


def verify_configuration(manifest, source):
    """Bind recorded workflow/configuration bytes to the authenticated source."""
    configuration = manifest['quality']['configuration']
    for path, expected in configuration['configuration_sources'].items():
        require(digest(source / path) == expected, 'Core configuration source differs: ' + path)
    for name, record in configuration['workflows'].items():
        path = source / '.github/workflows' / name
        require(digest(path) == record['sha256'] and
                path.read_text(encoding='utf-8') == record['definition'],
                'Core workflow differs from authenticated source: ' + name)


def compatible(record, probe, shared, configuration):
    if platform.system() not in ('Windows', 'Linux'):
        return False
    architecture = probe.get('COMPILER_ARCHITECTURE') or probe.get('PROCESSOR', '')
    if (probe.get('CROSS_COMPILING') != 'FALSE' or
            probe.get('SYSTEM') != platform.system() or
            architecture.lower() not in ('amd64', 'x86_64', 'x64')):
        return False
    # A static archive loaded into a Python module must be position independent.
    # The initial Core producer does not declare PIC; never infer it from x64.
    if shared == 'OFF' and platform.system() != 'Windows' and record.get('position_independent_code') is not True:
        return False
    system = 'windows' if platform.system() == 'Windows' else 'linux'
    expected = f"{system}-x64-{'shared' if shared == 'ON' else 'static'}"
    return (record.get('id') == expected and record.get('architecture') == 'x64' and
            platform.machine().lower() in ('x86_64', 'amd64') and probe['SIZEOF_DATA_PTR'] == '8' and
            record.get('os') == system and record.get('build_type') == configuration == 'Release' and
            record.get('linkage') == ('shared' if shared == 'ON' else 'static') and
            record.get('compiler', {}).get('CMAKE_C_COMPILER_ID') == probe['COMPILER_ID'] and
            record.get('compiler', {}).get('CMAKE_C_COMPILER_VERSION') == probe['COMPILER_VERSION'] and
            (record.get('msvc_runtime') == 'MultiThreadedDLL' if system == 'windows' else
             record.get('libc') == list(platform.libc_ver())) and
            all(record.get('options', {}).get(feature) == 'ON' for feature in REQUIRED_FEATURES))


def authenticated_release(work, selected):
    work.mkdir(parents=True, exist_ok=False)
    release = api(f"repos/{REPOSITORY}/releases/tags/{selected['release_tag']}")
    require(not release.get('draft') and release.get('tag_name') == selected['release_tag'], 'Core release unavailable')
    resolved = api(f"repos/{REPOSITORY}/commits/{selected['release_tag']}")
    require(resolved.get('sha') == selected['commit'], 'Core tag moved away from locked commit')

    def download(name):
        safe_name(name)
        require(sum(a['name'] == name for a in release['assets']) == 1, 'Missing/duplicate Core release asset: ' + name)
        path = work / name
        run('gh', 'release', 'download', selected['release_tag'], '--repo', REPOSITORY,
            '--pattern', name, '--dir', work)
        run('gh', 'attestation', 'verify', path, '--repo', REPOSITORY,
            '--signer-workflow', SIGNER, '--source-digest', selected['commit'])
        return path

    manifest_path = download('release-manifest.json')
    sums_path = download('SHA256SUMS')
    sums = checksums(sums_path)
    require(sums.get(manifest_path.name) == digest(manifest_path), 'Core manifest checksum mismatch')
    manifest = read(manifest_path)
    verify_manifest(manifest, selected)
    return manifest, sums, download, {'release_id': release['id'], 'manifest_sha256': digest(manifest_path)}


def resolve(work, probe, configuration):
    """Resolve an authenticated static dependency for the actual consumer compiler."""
    selected = lock(True)
    manifest, sums, download, release_identity = authenticated_release(work, selected)
    binaries = [r for r in manifest['artifacts'] if r.get('kind') == 'binary' and
                compatible(r, probe, 'OFF', configuration)]
    require(len(binaries) <= 1, 'Ambiguous compatible Core binary')
    if binaries:
        record, mode = binaries[0], 'verified-binary'
    else:
        require(selected['allow_verified_source'], 'No compatible binary and Verified Source fallback disabled')
        sources = [r for r in manifest['artifacts'] if r.get('kind') == 'source']
        require(len(sources) == 1, 'Expected one Verified Source artifact')
        record, mode = sources[0], 'verified-source'
    artifact = download(record['filename'])
    require(digest(artifact) == record['sha256'] == sums.get(artifact.name), 'Core archive checksum mismatch')
    destination = work / 'extracted'
    extract(artifact, destination)
    if mode == 'verified-source':
        source = destination / ('OpenTLV-' + manifest['version'])
        require((source / 'opentlv-source.txt').read_text() ==
                f"version={manifest['version']}\ncommit={selected['commit']}\n", 'Wrong extracted Core identity')
        location = {'source_dir': str(source.resolve())}
    else:
        configs = list(destination.rglob('OpenTLVConfig.cmake'))
        require(len(configs) == 1, 'Expected one Core package configuration')
        # Explicit package directory; CMake must not silently fall back to Git.
        location = {'package_dir': str(configs[0].parent.resolve())}
        # The public Query facade consumes shared fixtures even with binary Core.
        sources = [r for r in manifest['artifacts'] if r.get('kind') == 'source']
        require(len(sources) == 1, 'Expected the matching Verified Source corpus')
        source_record = sources[0]
        source_archive = download(source_record['filename'])
        require(digest(source_archive) == source_record['sha256'] == sums.get(source_archive.name),
                'Core corpus archive checksum mismatch')
        extract(source_archive, work / 'corpus')
        source = work / 'corpus' / ('OpenTLV-' + manifest['version'])
        require((source / 'opentlv-source.txt').read_text() ==
                f"version={manifest['version']}\ncommit={selected['commit']}\n", 'Wrong corpus identity')
    verify_configuration(manifest, source)
    evidence = {'mode': mode, 'verified': True, 'version': selected['version'],
                'repository': REPOSITORY, 'commit': selected['commit'], **location,
                'release_tag': selected['release_tag'], **release_identity,
                'signer_workflow': SIGNER,
                'artifact': record, 'probe': probe, 'source_path': str(source.resolve())}
    write(work / 'verification.json', evidence)
    return evidence
