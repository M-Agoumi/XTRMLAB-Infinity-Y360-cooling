# Contributing

Thanks for helping out. This project drives the round LCD on an AIO
cooler's pump cap (USB HID `5131:2007`) from Python instead of the
vendor's PC Monitor app. Bug reports, reports from other coolers, docs
fixes and code are all welcome.

## Ways to help

- **Report a bug** or **request a feature** with the
  [issue forms](https://github.com/M-Agoumi/XTRMLAB-Infinity-Y360-cooling/issues/new/choose).
- **Test on your hardware.** Reports from coolers, panels or
  motherboards we haven't seen are very useful, even when everything
  works. `RUN_DOCTOR.bat` output is the most helpful thing to attach.
- **Pick up an issue** labelled `good first issue` or `help wanted`.
  Comment on it first so two people don't do the same work.
- **Security issues** go through a
  [private advisory](https://github.com/M-Agoumi/XTRMLAB-Infinity-Y360-cooling/security/advisories/new), not a public issue.

## Branches

| Branch | Purpose |
| --- | --- |
| `develop` | Integration branch. **All PRs target `develop`.** |
| `main` | Released code. Only updated by a release PR from `develop` (or an urgent hotfix). |
| `v*` tags | A release on `main`, published with `PUBLISH_RELEASE.bat`. |

Neither `develop` nor `main` accepts direct pushes. Everything goes through a pull
request, reviewed by a code owner (see `.github/CODEOWNERS`). The
protection settings live in [`.github/rulesets/`](.github/rulesets/README.md).

## Development setup

You need Windows and the panel to run anything against real hardware.

```bat
git clone https://github.com/<you>/XTRMLAB-Infinity-Y360-cooling.git
cd XTRMLAB-Infinity-Y360-cooling
git checkout develop
INSTALL.bat
RUN_DOCTOR.bat
```

`INSTALL.bat` installs the Python packages and fetches
`LibreHardwareMonitorLib.dll`; `RUN_DOCTOR.bat` says what's still
missing. Close the vendor PC Monitor app first: two writers interleave
frames rather than erroring out. See the README's **Install** and
**Quick start** sections for the rest.

## Testing a change

There's no automated test suite yet, so say in the PR what you ran and
what the panel showed. Useful checks:

- `RUN_TEST.bat` posts a test frame.
- `RUN_DEMO.bat` shows live stats.
- `RUN_SENSORS.bat` (elevated) lists the sensors your board exposes.
- `BUILD_EXE.bat` if you touched anything the exe bundles.

Without a panel you can still review protocol logic against
[FINDINGS.md](FINDINGS.md), but please say the change wasn't tried on
hardware.

## Making a pull request

1. Fork the repo and create a branch from `develop`:
   `git checkout -b fix/short-description develop`
2. Keep the change focused. One fix or feature per PR is much easier to
   review than several.
3. Update the README or FINDINGS.md if behaviour or protocol notes change.
4. Open the PR **against `develop`** and fill in the template.
5. A code owner must approve before it can merge.

Branch name prefixes: `fix/`, `feature/`, `docs/`, `test/`.

## Ground rules

- **Display only.** Don't add anything that sends commands which could
  change pump or fan behaviour; see "Notes and limits" in the README.
- **No vendor code.** This is an interoperability reimplementation.
  Describe wire formats; don't paste or redistribute code or binaries
  from PC Monitor.
- **No new dependencies for driving the panel.** HID access stays on
  Windows' own `hid.dll` via ctypes. Extras can use packages, listed in
  `requirements.txt` with what they're for.

By contributing you agree your work is released under the
[MIT licence](LICENSE).
