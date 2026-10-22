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
