"""One check for the single-instance lock: the second process must exit(1)."""
import os, sys, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.utils.single_instance import claim_single_instance

HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = "from app.utils.single_instance import claim_single_instance; claim_single_instance(); print('claimed')"


def _child(env=None):
    return subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, cwd=HERE, env=env)


def test_second_instance_refuses_to_start():
    claim_single_instance()
    claim_single_instance()  # already held by this process - must be a no-op, not an exit
    r = _child()
    assert r.returncode == 1, f"second instance was allowed in: {r.stdout}{r.stderr}"


def test_bypass_env_var():
    r = _child(env=dict(os.environ, ALLOW_MULTIPLE_INSTANCES="1"))
    assert r.returncode == 0 and "claimed" in r.stdout, r.stderr


if __name__ == "__main__":
    test_second_instance_refuses_to_start()
    test_bypass_env_var()
    print("ok")
