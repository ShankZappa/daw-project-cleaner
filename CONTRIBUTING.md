# Contributing

Contributions that improve safe, auditable interoperability are welcome.

## Ground rules

- Submit only code and data you have the right to share.
- Never commit real customer projects, audio, server paths or application files.
- Use generated minimal fixtures for tests.
- Do not add license bypass, activation, DRM circumvention or application-binary
  modification features.
- Unknown formats must fail closed and remain report-only.
- New format claims require reproducible tests and a documented fingerprint.
- Keep product/trademark references factual and preserve the independent-project
  disclaimer.

Run before submitting:

```bash
python3 -m unittest discover -v
swiftc -typecheck native/App.swift
```

By contributing, you agree that your contribution is licensed under the MIT
License and that you have the right to provide it.
