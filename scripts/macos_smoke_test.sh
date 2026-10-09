#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 (--workspace <path> | --project <path>) --scheme <name> [--destination <value>] [--configuration <name>] [--derived-data <path>] [--require-resource <app-relative-path>] [--allow-signing] [--test] [--only-testing <target[/class[/method]]>] [--test-timeout <seconds>] [--result-bundle <path>] [--verbose]"
}

container_kind=""
container_path=""
scheme=""
destination="generic/platform=iOS"
destination_supplied=0
configuration="Debug"
derived_data=""
result_bundle=""
test_timeout="60"
allow_signing=0
verbose=0
action="build"
only_testing=()
required_resources=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace|--project)
      if [[ "$1" == "--workspace" ]]; then
        container_kind="-workspace"
      else
        container_kind="-project"
      fi
      [[ $# -ge 2 ]] || { usage; exit 2; }
      container_path="$2"
      shift 2
      ;;
    --scheme)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      scheme="$2"
      shift 2
      ;;
    --destination)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      destination="$2"
      destination_supplied=1
      shift 2
      ;;
    --configuration)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      configuration="$2"
      shift 2
      ;;
    --derived-data)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      derived_data="$2"
      shift 2
      ;;
    --result-bundle)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      result_bundle="$2"
      shift 2
      ;;
    --require-resource)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      required_resources+=("$2")
      shift 2
      ;;
    --only-testing)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      only_testing+=("$2")
      action="test"
      shift 2
      ;;
    --test-timeout)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      test_timeout="$2"
      shift 2
      ;;
    --allow-signing) allow_signing=1; shift ;;
    --test) action="test"; shift ;;
    --verbose) verbose=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

[[ "$(uname -s)" == "Darwin" ]] || { echo "error: macOS with Xcode is required" >&2; exit 2; }
command -v xcodebuild >/dev/null || { echo "error: xcodebuild is unavailable" >&2; exit 2; }
[[ -n "$container_kind" && -n "$container_path" && -n "$scheme" ]] || { usage; exit 2; }
[[ -e "$container_path" ]] || { echo "error: container not found: $container_path" >&2; exit 2; }
[[ "$test_timeout" =~ ^[1-9][0-9]*$ ]] || { echo "error: --test-timeout must be a positive integer" >&2; exit 2; }
if [[ "$action" == "test" && $destination_supplied -eq 0 ]]; then
  echo "error: --test requires an explicit runnable simulator or device --destination; generic/platform=iOS cannot execute tests" >&2
  exit 2
fi
if [[ -n "$result_bundle" && -e "$result_bundle" ]]; then
  echo "error: result bundle path already exists: $result_bundle" >&2
  exit 2
fi
if [[ ${#required_resources[@]} -gt 0 && -z "$derived_data" ]]; then
  echo "error: --require-resource requires an explicit isolated --derived-data path" >&2
  exit 2
fi
for resource in "${required_resources[@]}"; do
  if [[ -z "$resource" || "$resource" == /* || "$resource" == ".." || "$resource" == ../* || "$resource" == */../* || "$resource" == */.. ]]; then
    echo "error: --require-resource must be a safe path relative to the built .app: $resource" >&2
    exit 2
  fi
done

args=("$container_kind" "$container_path" -scheme "$scheme" -configuration "$configuration" -destination "$destination" "$action")
if [[ $verbose -eq 0 ]]; then
  args+=( -quiet )
fi
if [[ -n "$derived_data" ]]; then
  args+=( -derivedDataPath "$derived_data" )
fi
if [[ $allow_signing -eq 0 ]]; then
  args+=( CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO )
fi
if [[ "$action" == "test" ]]; then
  args+=( -test-timeouts-enabled YES -default-test-execution-time-allowance "$test_timeout" -maximum-test-execution-time-allowance "$test_timeout" )
  for test_identifier in "${only_testing[@]}"; do
    args+=( "-only-testing:$test_identifier" )
  done
fi
if [[ -n "$result_bundle" ]]; then
  args+=( -resultBundlePath "$result_bundle" )
fi

echo "Running '$action' for scheme '$scheme' on '$destination'."
xcodebuild "${args[@]}"

if [[ ${#required_resources[@]} -gt 0 ]]; then
  products_root="$derived_data/Build/Products"
  app_products=()
  if [[ -d "$products_root" ]]; then
    while IFS= read -r -d '' app_product; do
      app_products+=("$app_product")
    done < <(find "$products_root" -type d -name '*.app' -print0)
  fi
  if [[ ${#app_products[@]} -eq 0 ]]; then
    echo "error: no built .app was found below: $products_root" >&2
    exit 1
  fi
  for resource in "${required_resources[@]}"; do
    resource_found=0
    for app_product in "${app_products[@]}"; do
      if [[ -e "$app_product/$resource" ]]; then
        echo "Verified app resource: $resource in $app_product"
        resource_found=1
        break
      fi
    done
    if [[ $resource_found -eq 0 ]]; then
      echo "error: required app resource was not found at relative path '$resource' in any built .app below: $products_root" >&2
      exit 1
    fi
  done
fi

if [[ "$action" == "test" ]]; then
  echo "Test step passed. Only the selected scheme/tests are covered; report untested device-only visual and performance paths separately."
else
  echo "Build step passed. This does not prove launch, UI interaction, runtime effects, camera orientation, license scope, or memory behavior."
fi
