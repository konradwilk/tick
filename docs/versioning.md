# Build versions

All five clients use [linux/tick/version.py](../linux/tick/version.py) to generate
the version shown in Settings. Python is required at build time; Git identifies
the version when building from a checkout.

The helper runs `git describe --tags --match RELEASE_* --always` and removes the
`RELEASE_` prefix. For example, `RELEASE_0.1` displays `0.1`; three commits later,
`RELEASE_0.1-3-gabcdef` displays `0.1-3-gabcdef`. Without an applicable release tag,
Git returns an abbreviated commit ID. The current helper does not append a dirty
working-tree marker.

When Git is unavailable, `linux/tick/_version.txt` supplies the version for a
source distribution. Without Git or a nonempty stamp, the version is `unknown`.
The stamp is generated distribution metadata and is ignored by Git.

Print the current version from the repository root:

```sh
python3 linux/tick/version.py
```

Use `python` on Windows if that is the installed interpreter command. The helper
also generates native source declarations:

```sh
python3 linux/tick/version.py --format swift --output /tmp/BuildVersion.swift
python3 linux/tick/version.py --format csharp --output /tmp/BuildVersion.g.cs
```

macOS uses `BuildVersionPlugin`; iOS runs the helper in its Xcode build phase;
Windows generates `BuildVersion.g.cs` before compilation; Android uses the text
output as its version name; Linux imports `source_version()` directly.
