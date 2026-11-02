#!/usr/bin/env bash
# Isolated integration tests: fake nginx, virtual /proc and a disposable master.
# No host service manager, screen session or nginx configuration is touched.
set -euo pipefail
repo=$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")
work=$(mktemp -d /tmp/poe2guild-tests.XXXXXX)
real_readlink=$(command -v readlink)
real_ps=$(command -v ps)
cleanup() {
    local result=$? pid args
    if [[ -f "$work/masters" ]]; then
        while read -r pid; do
            args=$("$real_ps" -p "$pid" -o args= 2>/dev/null || true)
            if [[ "$args" == *"$work/fake-master"* ]]; then kill -TERM "$pid" 2>/dev/null || true; fi
        done < "$work/masters"
    fi
    [[ "$work" == /tmp/poe2guild-tests.* && -d "$work" ]] || return "$result"
    rm -rf -- "$work"
    return "$result"
}
trap cleanup EXIT
project="$work/project space"
mkdir -p "$project/venv/bin" "$project/scripts" "$project/frontend/dist" "$work/bin" "$work/proc"
touch "$project/frontend/dist/index.html"
# Replace only OS-specific paths inside the test copy, never in the real script.
sed -e "s|/proc/|$work/proc/|g" \
    -e "s|/run/lock/poe2guild-nginx.lock|$work/nginx.lock|g" \
    "$repo/poe2guild" > "$project/poe2guild"
cp "$repo/scripts/nginx-route.awk" "$project/scripts/"
chmod +x "$project/poe2guild"
export TEST_WORK="$work" TEST_PROJECT="$project" REAL_READLINK="$real_readlink"
export MOCK_LOG="$work/commands.log" NGINX_TARGET="$work/services"
cat > "$work/bin/mock" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
name=${0##*/}
case "$name" in
    uname) printf 'Linux\n' ;;
    id) if [[ "$1" == -u ]]; then printf '%s\n' "${MOCK_UID:-1000}"; else printf 'test-account\n'; fi ;;
    stat) if [[ "${*: -1}" == "$TEST_WORK/proc/"* ]]; then printf '1000\n'; else printf '0\n'; fi ;;
    readlink)
        if [[ "${*: -1}" == "$TEST_WORK/proc/"*/cwd ]]; then
            pid=${*: -1}; pid=${pid%/cwd}; cat "$pid/cwd-value"
        else exec "$REAL_READLINK" "$@"; fi ;;
    ps)
        if [[ -f "$TEST_WORK/proc/$2/args" ]]; then cat "$TEST_WORK/proc/$2/args"; else exit 1; fi ;;
    sudo)
        printf 'sudo\n' >> "$MOCK_LOG"
        [[ "${1:-}" != -- ]] || shift
        exec env MOCK_UID=0 "$@" ;;
    curl) [[ "${MOCK_HEALTH_FAIL:-0}" == 0 ]] ;;
    nginx)
        printf 'nginx|%s\n' "$*" >> "$MOCK_LOG"
        if [[ -n "${MOCK_FAIL_TEST_MATCH:-}" && "$1" == -t ]] && grep -Fq -- "$MOCK_FAIL_TEST_MATCH" "$NGINX_TARGET"; then exit 7; fi
        if [[ -n "${MOCK_FAIL_RELOAD_MATCH:-}" && "$1" == -s ]] && grep -Fq -- "$MOCK_FAIL_RELOAD_MATCH" "$NGINX_TARGET"; then exit 8; fi ;;
    flock) : ;;
    *) printf 'Unexpected tool: %s\n' "$name" >&2; exit 1 ;;
esac
EOF
for name in uname id stat readlink ps sudo curl nginx flock; do
    cp "$work/bin/mock" "$work/bin/$name"; chmod +x "$work/bin/$name"
done
cat > "$work/fake-master" <<'EOF'
#!/usr/bin/env bash
trap 'rm -f -- "$1"; exit 0' TERM
while :; do sleep 0.1; done
EOF
chmod +x "$work/fake-master"
cat > "$project/venv/bin/gunicorn" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'gunicorn\n' >> "$MOCK_LOG"
pidfile=''
while (($#)); do
    if [[ "$1" == --pid ]]; then pidfile=$2; shift 2; else shift; fi
done
[[ -n "$pidfile" ]]
"$TEST_WORK/fake-master" "$pidfile" </dev/null >/dev/null 2>&1 &
pid=$!
printf '%s\n' "$pid" >> "$TEST_WORK/masters"
mkdir -p "$TEST_WORK/proc/$pid"
printf '%s\n' "$TEST_PROJECT" > "$TEST_WORK/proc/$pid/cwd-value"
printf 'gunicorn: master [app:app]\n' > "$TEST_WORK/proc/$pid/args"
{ printf '%s (gunicorn) ' "$pid"; for _ in {1..19}; do printf '0 '; done; printf '12345\n'; } > "$TEST_WORK/proc/$pid/stat"
printf '%s\n' "$pid" > "$pidfile"
EOF
chmod +x "$project/venv/bin/gunicorn"
cat > "$project/venv/bin/python" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == -c ]]; then exit "${MOCK_WORKER_HEALTH_FAIL:-0}"; fi
if [[ "$1" != -m ]]; then printf '{}\n'; exit 0; fi
printf 'worker\n' >> "$MOCK_LOG"
pid=$$
printf '%s\n' "$pid" >> "$TEST_WORK/masters"
mkdir -p "$TEST_WORK/proc/$pid"
printf '%s\n' "$TEST_PROJECT" > "$TEST_WORK/proc/$pid/cwd-value"
printf 'python -m backend.worker\n' > "$TEST_WORK/proc/$pid/args"
{ printf '%s (python) ' "$pid"; for _ in {1..19}; do printf '0 '; done; printf '12345\n'; } > "$TEST_WORK/proc/$pid/stat"
exec "$TEST_WORK/fake-master" "$TEST_PROJECT/.run/worker.pid"
EOF
chmod +x "$project/venv/bin/python"
export PATH="$work/bin:$PATH"
: > "$MOCK_LOG"
settings() {
    cat > "$project/service.ini" <<EOF
[service]
bind = ${1:-127.0.0.1:9001}
venv = venv
url_prefix = /poe2-guild
nginx_file = $work/services
nginx_server = ${2:-}
EOF
}
settings
cat > "$work/original" <<'EOF'
# Shared configuration; unrelated content must survive.
server {
    listen 443 ssl;
    server_name example.test;
    location = / { return 404; }
    location /other/ { proxy_pass http://127.0.0.1:8002/; }
    location /poe2-guild/ {
        proxy_pass http://127.0.0.1:9001/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        auth_basic "Private {area}";
    }
    location = /poe2-guild { return 301 /poe2-guild/; }
}
EOF
cp "$work/original" "$work/services"
assert_contains() { grep -Fq -- "$2" "$1" || { printf 'Missing: %s\n' "$2" >&2; exit 1; }; }
assert_absent() { if grep -Fq -- "$2" "$1"; then printf 'Unexpected: %s\n' "$2" >&2; exit 1; fi; }
expect_exit() {
    local expected=$1 result=0; shift
    "$@" > "$work/output" 2>&1 || result=$?
    [[ "$result" == "$expected" ]] || { cat "$work/output"; printf 'Expected %s, got %s\n' "$expected" "$result" >&2; exit 1; }
}

cd "$work"
expect_exit 3 "$project/poe2guild" status
"$project/poe2guild" start > "$work/output"
read -r pid < "$project/.run/gunicorn.pid"
"$project/poe2guild" status > "$work/output"
assert_contains "$work/output" "Running: PID $pid"
assert_contains "$work/output" 'Worker running:'
read -r worker_pid < "$project/.run/worker.pid"
worker_session=$("$real_ps" -p "$worker_pid" -o sid=)
[[ "${worker_session//[[:space:]]/}" == "$worker_pid" ]] # Survives the caller's process-group cleanup.
MOCK_WORKER_HEALTH_FAIL=1 expect_exit 1 "$project/poe2guild" status
"$project/poe2guild" start > "$work/output"
[[ $(grep -c '^gunicorn$' "$MOCK_LOG") == 1 ]]
[[ $(grep -c '^worker$' "$MOCK_LOG") == 1 ]]
assert_absent "$MOCK_LOG" sudo
MOCK_HEALTH_FAIL=1 expect_exit 1 "$project/poe2guild" status
"$project/poe2guild" restart > "$work/output"
[[ $(grep -c '^gunicorn$' "$MOCK_LOG") == 2 ]]
[[ $(grep -c '^worker$' "$MOCK_LOG") == 2 ]]
"$project/poe2guild" stop > "$work/output"
expect_exit 3 "$project/poe2guild" status
MOCK_UID=0 expect_exit 1 "$project/poe2guild" start

# Do not signal a PID file pointing at a process from another checkout.
"$project/poe2guild" start > "$work/output"
read -r pid < "$project/.run/gunicorn.pid"
printf '/unrelated/checkout\n' > "$work/proc/$pid/cwd-value"
"$project/poe2guild" stop > "$work/output"
kill -0 "$pid"
printf '%s\n' "$project" > "$work/proc/$pid/cwd-value"
printf '%s\n' "$pid" > "$project/.run/gunicorn.pid"
printf '%s 12345\n' "$pid" > "$project/.run/gunicorn.identity"
"$project/poe2guild" stop > "$work/output"

# A worker from another checkout must never be signaled by stop.
"$project/poe2guild" start > "$work/output"
read -r worker_pid < "$project/.run/worker.pid"
printf '/unrelated/checkout\n' > "$work/proc/$worker_pid/cwd-value"
"$project/poe2guild" stop > "$work/output"
kill -0 "$worker_pid"
printf '%s\n' "$project" > "$work/proc/$worker_pid/cwd-value"
printf '%s\n' "$worker_pid" > "$project/.run/worker.pid"
printf '%s 12345\n' "$worker_pid" > "$project/.run/worker.identity"
"$project/poe2guild" stop > "$work/output"
"$project/poe2guild" start > "$work/output"
read -r worker_pid < "$project/.run/worker.pid"
kill -TERM "$worker_pid"
sleep .3
expect_exit 1 "$project/poe2guild" status
web_starts=$(grep -c '^gunicorn$' "$MOCK_LOG")
"$project/poe2guild" start > "$work/output"
[[ $(grep -c '^gunicorn$' "$MOCK_LOG") == "$web_starts" ]]
"$project/poe2guild" stop > "$work/output"

# Existing locations, including custom access controls, are not rewritten.
"$project/poe2guild" install > "$work/output"
assert_contains "$MOCK_LOG" sudo
cmp "$work/original" "$work/services"
[[ $(grep -c 'location /poe2-guild/' "$work/services") == 1 ]]
assert_contains "$work/services" 'location /other/ { proxy_pass http://127.0.0.1:8002/; }'
"$project/poe2guild" uninstall > "$work/output"
assert_absent "$work/services" 'poe2-guild'
"$project/poe2guild" install > "$work/output"
assert_contains "$work/services" '# BEGIN poe2guild /poe2-guild'
cp "$work/services" "$work/installed"
"$project/poe2guild" install > "$work/output"
cmp "$work/installed" "$work/services"

# Failed validation/reload restores the shared file exactly.
settings 127.0.0.1:9999
MOCK_FAIL_TEST_MATCH=127.0.0.1:9999 expect_exit 7 "$project/poe2guild" install
cmp "$work/installed" "$work/services"
MOCK_FAIL_RELOAD_MATCH=127.0.0.1:9999 expect_exit 8 "$project/poe2guild" install
cmp "$work/installed" "$work/services"
settings
"$project/poe2guild" uninstall > "$work/output"
assert_absent "$work/services" 'poe2-guild'
assert_contains "$work/services" 'location /other/'
cp "$work/services" "$work/uninstalled"
"$project/poe2guild" uninstall > "$work/output"
cmp "$work/uninstalled" "$work/services"

# Conflicting unmanaged route is never overwritten.
sed 's/127.0.0.1:9001/127.0.0.1:9876/' "$work/original" > "$work/services"
cp "$work/services" "$work/conflict"
expect_exit 2 "$project/poe2guild" install
cmp "$work/conflict" "$work/services"

# Several servers require explicit selection and preserve the other server.
cat "$work/original" > "$work/services"
printf '\nserver { server_name second.test; location / { return 404; } }\n' >> "$work/services"
expect_exit 2 "$project/poe2guild" install
settings 127.0.0.1:9001 example.test
"$project/poe2guild" install --dry-run > "$work/candidate"
assert_contains "$work/candidate" 'server { server_name second.test; location / { return 404; } }'
assert_absent "$work/services" '# BEGIN poe2guild'
"$project/poe2guild" install > "$work/output"
cmp "$work/candidate" "$work/services"

# Missing redirect can be added without losing access controls on a legacy proxy.
sed '/location = \/poe2-guild { return 301/d' "$work/original" > "$work/services"
settings
"$project/poe2guild" install > "$work/output"
assert_contains "$work/services" 'auth_basic "Private {area}";'
[[ $(grep -c 'location /poe2-guild/' "$work/services") == 1 ]]
cp "$work/services" "$work/partial"
"$project/poe2guild" install > "$work/output"
cmp "$work/partial" "$work/services"

# Prefix-sharing routes must not be mistaken for one another's owned markers.
sed -e 's|/poe2-guild|/poe2-guild-extra|g' "$work/installed" > "$work/services"
"$project/poe2guild" uninstall > "$work/output"
assert_contains "$work/services" '# BEGIN poe2guild /poe2-guild-extra'
assert_contains "$work/services" 'location /poe2-guild-extra/'
printf 'Local process lifecycle and transactional nginx checks passed.\n'
