# Privacy

DAW Project Cleaner processes project files locally on the user's Mac.

It does not:

- upload projects, audio, paths or reports;
- collect analytics or crash telemetry;
- create an account or device identifier;
- contact a licensing, update or advertising server;
- embed third-party tracking SDKs.

The app writes one JSON report under the current user's Application Support
folder. That report can include absolute project/media paths, filenames, sizes,
hashes and detected product versions. Anyone receiving the report may learn
sensitive archive information, so redact it before sharing.

The **About & Support** button displays a bundled QR image. Only pressing **Open
Buy Me a Coffee** opens the system browser to
`https://buymeacoffee.com/franckreisner`. The scanner itself performs no network
request.

Deleting the report is optional and does not affect the project archive.
