"""Exercise the installer's launchd restart against a stateful launchctl stand-in."""
import pathlib
import shutil
import subprocess
import unittest

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "postinstall"


@unittest.skipUnless(shutil.which("zsh"), "zsh is required")
class RestartTests(unittest.TestCase):
    def run_restart(self, *, delayed=0, failures=0, stuck=False, invisible=False):
        source = SCRIPT.read_text()
        function = source[source.index("reload_job() {"):source.index("\n# The agent runs as root")]
        function = function.replace("/bin/sleep 1", ":")
        harness = f'''
ROOT=""
loaded=1
remaining={delayed}
failures={failures}
stuck={int(stuck)}
invisible={int(invisible)}
boots=0
log() {{ print -r -- "$1"; }}
launchctl_run() {{
    case "$1" in
        bootout) return 0 ;;
        print)
            if (( stuck )); then return 0; fi
            if (( boots == 0 )); then
                if (( remaining > 0 )); then (( remaining-- )); return 0; fi
                loaded=0
            fi
            (( loaded && !invisible ))
            return $?
            ;;
        bootstrap)
            (( boots++ ))
            if (( boots <= failures )); then return 5; fi
            loaded=1
            return 0
            ;;
    esac
    return 9
}}
{function}
reload_job example.beacon /example.plist
result=$?
print -r -- "RESULT=$result BOOTS=$boots"
'''
        result = subprocess.run(["zsh", "-c", harness], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_waits_for_old_job_and_retries_transient_bootstrap_failure(self):
        self.assertIn("RESULT=0 BOOTS=3", self.run_restart(delayed=3, failures=2))

    def test_fresh_load_succeeds(self):
        self.assertIn("RESULT=0 BOOTS=1", self.run_restart())

    def test_permanent_bootstrap_failure_is_bounded_and_fails(self):
        output = self.run_restart(failures=99)
        self.assertIn("ERROR:", output)
        self.assertIn("RESULT=1 BOOTS=15", output)

    def test_old_job_that_never_unloads_is_not_reported_successful(self):
        self.assertIn("RESULT=1 BOOTS=0", self.run_restart(stuck=True))

    def test_bootstrap_success_without_registered_job_is_not_success(self):
        self.assertIn("RESULT=1 BOOTS=15", self.run_restart(invisible=True))


if __name__ == "__main__":
    unittest.main()
