"""
Tests for the deployer protocol and client.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from app.deployment.client import DeployerClient


class TestDeployerClient:
    """Tests for DeployerClient."""

    def test_submit_job_includes_args(self, tmp_path):
        """submit_job passes args dict to the deployer socket request."""
        sock_path = tmp_path / "deployer.sock"
        sock_path.touch()

        with patch("app.deployment.client.socket.socket") as mock_sock_class:
            mock_sock = MagicMock()
            mock_sock.__enter__.return_value = mock_sock
            mock_sock.__exit__.return_value = False
            mock_sock_class.return_value = mock_sock
            mock_sock.recv.return_value = b'{"job_id": "abc", "status": "succeeded"}\n'

            client = DeployerClient(str(sock_path))
            result = client.submit_job(
                {"job_id": "abc", "job_type": "create_system_worktree"},
                args={"RUN_ID": "run-123"},
            )

            call_args = mock_sock.sendall.call_args[0][0]
            sent = json.loads(call_args.decode())
            assert sent["args"]["RUN_ID"] == "run-123"

    def test_submit_job_no_args(self, tmp_path):
        """submit_job works without args (same defaults as minimal callers)."""
        sock_path = tmp_path / "deployer.sock"
        sock_path.touch()

        with patch("app.deployment.client.socket.socket") as mock_sock_class:
            mock_sock = MagicMock()
            mock_sock.__enter__.return_value = mock_sock
            mock_sock.__exit__.return_value = False
            mock_sock_class.return_value = mock_sock
            mock_sock.recv.return_value = b'{"job_id": "abc", "status": "succeeded"}\n'

            client = DeployerClient(str(sock_path))
            result = client.submit_job({"job_id": "abc", "job_type": "rebuild_agent_space"})

            call_args = mock_sock.sendall.call_args[0][0]
            sent = json.loads(call_args.decode())
            assert "args" not in sent

    def test_available_returns_false_when_socket_missing(self, tmp_path):
        """available is False when socket path does not exist."""
        client = DeployerClient(str(tmp_path / "nonexistent.sock"))
        assert client.available is False

    def test_available_returns_true_when_socket_exists(self, tmp_path):
        """available is True when socket file exists."""
        sock_path = tmp_path / "deployer.sock"
        sock_path.touch()
        client = DeployerClient(str(sock_path))
        assert client.available is True

    def test_submit_job_returns_failed_when_unavailable(self, tmp_path):
        """submit_job returns failed result when socket is not available."""
        client = DeployerClient(str(tmp_path / "nonexistent.sock"))
        result = client.submit_job({"job_id": "abc", "job_type": "health_check"})
        assert result["status"] == "failed"
        assert "not found" in result["error"]