#!/bin/bash

# Run the two prespecified Social/Monetary Doors randomise analyses.

set -euo pipefail

scriptdir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

bash "${scriptdir}/L3stats.sh"
