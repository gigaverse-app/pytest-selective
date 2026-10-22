# Provenance

The initial implementation and tests were extracted from Gigaverse's
backend-common commit d4da0ef72199a73eabc8ca1d90e5bcd956955832, with authorization to open-source this infrastructure.

The initial extraction keeps algorithm and configuration semantics intact, replaces
the backend_common.testing import namespace with pytest_selective, and adds
standalone packaging. Existing gv:test-dependency comments and
.gv-dependency.yaml / .gv-dependencies.yaml declarations remain supported.

The package owns dependency analysis, selection, audit, explanation, test-file
discovery, shard planning, and the related type-check selection CLI.
Application-specific service routing, credentials, deployments, and private
repository history are excluded. The optional audit recorder loads explicitly;
installing the package does not automatically alter pytest collection.

Copyright Gigaverse. Licensed under Apache-2.0; see LICENSE.

The global pytest expansion guard and test-file import-isolation checks were extracted
from backend-common b6a2de0f58f18b78e544568d9ebd7371c8c30370 via CI-esta
a9e6f656532aac521163280178f643149da34114. Their original behavioral tests move
with them. CI-esta retains compatibility delegates; pytest-selective owns these
guards because they preserve the assumptions behind file-level test selection.
