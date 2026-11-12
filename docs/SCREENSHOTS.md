# Screenshot policy

NetWatch displays live host and network state. An unmodified capture can expose the
operator's hostname, adapter names, private and public addresses, MAC addresses, process
names, and remote endpoints. Authentic captures are therefore kept out of the published
repository and matched by `.gitignore`.

No screenshots are captured for the public release, because an authentic capture must come
from a real machine and redaction has to happen before publication, not by editing evidence
afterward.

If you publish your own screenshots:

- run NetWatch on an isolated lab network that you own;
- use non-identifying host and device names;
- disable public-IP lookup, or mask the value;
- review adapter names, process names, local and remote endpoints, and alert text;
- mask addresses and identifiers before sharing;
- never edit an image to imply telemetry that did not occur.

The public README documents the interface and behavior without reproducing sensitive
network data.
