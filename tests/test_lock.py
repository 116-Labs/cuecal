import pytest

from cuecal.lock import LockContentionError, SingleInstanceLock


def test_lock_acquire_and_release(tmp_path):
    lock_file = tmp_path / "test.lock"
    lock1 = SingleInstanceLock(lock_file)
    assert lock1.acquire() is True
    assert lock_file.exists()

    # Second instance cannot acquire while first holds it
    lock2 = SingleInstanceLock(lock_file)
    assert lock2.acquire() is False

    # Once released, second instance can acquire
    lock1.release()
    assert lock2.acquire() is True
    lock2.release()


def test_lock_context_manager(tmp_path):
    lock_file = tmp_path / "test.lock"
    with SingleInstanceLock(lock_file):
        assert lock_file.exists()
        lock2 = SingleInstanceLock(lock_file)
        with pytest.raises(LockContentionError):
            with lock2:
                pass

    # After exiting with block, lock is available again
    with SingleInstanceLock(lock_file):
        pass


def test_lock_creates_parent_directories(tmp_path):
    lock_file = tmp_path / "nested" / "dir" / "test.lock"
    lock = SingleInstanceLock(lock_file)
    assert lock.acquire() is True
    lock.release()
    assert lock_file.exists()
