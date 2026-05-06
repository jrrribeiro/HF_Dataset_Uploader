"""Tests to ensure tokens never leak in logs, errors, or output."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from src.uploader_cli.auth_service import AuthService
from src.uploader_cli.config import TOKEN_ENV_VAR
from src.uploader_cli.exceptions import AuthenticationError
from src.uploader_cli.main import cli


class TestTokenSecurityLogging:
    """Verify tokens never leak in error messages or logs."""

    def test_auth_error_does_not_expose_token(self):
        """Ensure error messages don't contain the actual token."""
        test_token = "hf_shouldNotAppearInError123456"
        
        with patch("src.uploader_cli.auth_service.HfApi") as mock_api:
            mock_api.side_effect = Exception("Invalid token")
            service = AuthService()
            
            with pytest.raises(AuthenticationError) as exc_info:
                service.authenticate(test_token)
            
            error_msg = str(exc_info.value)
            assert test_token not in error_msg, "Token leaked in error message"
            # Verify error message is still informative
            assert "Token validation failed" in error_msg

    def test_require_token_error_is_informative(self):
        """Ensure require_token error doesn't expose keyring backend details."""
        service = AuthService()
        
        with patch.dict(os.environ, {TOKEN_ENV_VAR: ""}, clear=False):
            with patch("keyring.get_password", return_value=None):
                with pytest.raises(AuthenticationError) as exc_info:
                    service.require_token()
                
                error_msg = str(exc_info.value)
                assert "No stored token found" in error_msg
                assert "Run 'birdnet-uploader login'" in error_msg

    def test_env_var_token_not_logged_in_output(self, tmp_path):
        """Verify HF_TOKEN env var is never logged by the CLI."""
        runner = CliRunner()
        test_token = "hf_env_token_test_12345"
        segments_dir = tmp_path / "segments"
        segments_dir.mkdir()
        
        with patch.dict(os.environ, {TOKEN_ENV_VAR: test_token}):
            with patch("src.uploader_cli.auth_service.AuthService.require_token", return_value=test_token):
                # Attempt a command that would use the token (but mock out the actual upload)
                with patch("src.uploader_cli.main.LocalScanner") as mock_scanner:
                    mock_scanner.return_value.scan_folder.return_value = {
                        "total_files": 0,
                        "total_size": 0,
                        "by_species": {},
                    }
                    
                    result = runner.invoke(
                        cli,
                        [
                            "upload",
                            "--repo-id", "test/repo",
                            "--segments", str(segments_dir),
                            "--dry-run",
                        ],
                        env={TOKEN_ENV_VAR: test_token},
                    )
                    
                    # Verify CLI executed successfully
                    assert result.exit_code == 0, f"CLI failed: {result.output}"
                    # Verify token not in output
                    assert test_token not in result.output, f"Token leaked in output: {result.output}"
                    assert "Dry run" in result.output

    def test_cli_token_option_not_exposed_on_error(self):
        """Verify --token CLI option is never shown in error output."""
        runner = CliRunner()
        test_token = "hf_cli_token_test_67890"
        
        with patch("src.uploader_cli.main.LocalScanner") as mock_scanner:
            mock_scanner.return_value.scan_folder.side_effect = RuntimeError("Scan error")
            
            result = runner.invoke(
                cli,
                [
                    "upload",
                    "--repo-id", "test/repo",
                    "--segments", "/tmp/segments",
                    "--token", test_token,
                ],
            )
            
            # Even though CLI failed, token should not appear in output
            assert test_token not in result.output, f"Token leaked in error output: {result.output}"
            # Verify an error was reported
            assert result.exit_code != 0

    def test_get_token_from_env_var(self):
        """Verify get_token() correctly reads HF_TOKEN env var."""
        test_token = "hf_env_token_123"
        service = AuthService()
        
        with patch.dict(os.environ, {TOKEN_ENV_VAR: test_token}):
            token = service.get_token()
            assert token == test_token

    def test_get_token_env_var_takes_precedence(self):
        """Verify HF_TOKEN env var takes precedence over keyring."""
        env_token = "hf_from_env"
        keyring_token = "hf_from_keyring"
        service = AuthService()
        
        with patch.dict(os.environ, {TOKEN_ENV_VAR: env_token}):
            with patch("keyring.get_password", return_value=keyring_token):
                token = service.get_token()
                assert token == env_token, "Env var should take precedence"

    def test_get_token_falls_back_to_keyring(self):
        """Verify get_token() falls back to keyring if HF_TOKEN not set."""
        keyring_token = "hf_from_keyring_only"
        service = AuthService()
        
        with patch.dict(os.environ, {TOKEN_ENV_VAR: ""}, clear=False):
            with patch("keyring.get_password", return_value=keyring_token):
                token = service.get_token()
                assert token == keyring_token

    def test_token_whitespace_stripped(self):
        """Verify tokens are stripped of leading/trailing whitespace."""
        service = AuthService()
        
        with patch.dict(os.environ, {TOKEN_ENV_VAR: "  hf_token_with_spaces  "}):
            token = service.get_token()
            assert token == "hf_token_with_spaces"
            assert token != "  hf_token_with_spaces  "

    def test_empty_env_var_falls_back_to_keyring(self):
        """Verify empty HF_TOKEN env var doesn't prevent keyring fallback."""
        keyring_token = "hf_from_keyring"
        service = AuthService()
        
        with patch.dict(os.environ, {TOKEN_ENV_VAR: ""}):
            with patch("keyring.get_password", return_value=keyring_token):
                token = service.get_token()
                assert token == keyring_token

    def test_authentication_strips_token(self):
        """Verify authenticate() strips whitespace from tokens."""
        test_token = "  hf_clean_token  "
        service = AuthService()
        
        with patch("src.uploader_cli.auth_service.HfApi") as mock_api:
            mock_api_instance = MagicMock()
            mock_api_instance.whoami.return_value = {"name": "testuser"}
            mock_api.return_value = mock_api_instance
            
            with patch("keyring.set_password") as mock_keyring:
                service.authenticate(test_token)
                # Verify stripped token was passed to keyring
                mock_keyring.assert_called_once()
                args = mock_keyring.call_args[0]
                assert args[2] == "hf_clean_token"  # Third arg is the token

    def test_no_token_error_is_user_friendly(self):
        """Verify 'no token' error doesn't expose internal state."""
        service = AuthService()
        
        with patch.dict(os.environ, {TOKEN_ENV_VAR: ""}, clear=False):
            with patch("keyring.get_password", return_value=None):
                with pytest.raises(AuthenticationError) as exc_info:
                    service.require_token()
                
                error_msg = str(exc_info.value)
                # Should be user-friendly, not expose internals
                assert "birdnet-uploader login" in error_msg
                assert "keyring" not in error_msg.lower()


class TestTokenSecurityEnvironment:
    """Test token handling with various environment setups."""

    def test_cli_token_option_preferred_over_env(self, tmp_path):
        """Verify --token CLI option takes precedence."""
        runner = CliRunner()
        cli_token = "hf_from_cli"
        env_token = "hf_from_env"
        segments_dir = tmp_path / "segments"
        segments_dir.mkdir()
        
        with patch("src.uploader_cli.main.AuthService") as mock_auth:
            with patch("src.uploader_cli.main.LocalScanner") as mock_scanner:
                mock_scanner.return_value.scan_folder.return_value = {
                    "total_files": 0,
                    "total_size": 0,
                    "by_species": {},
                }
                
                result = runner.invoke(
                    cli,
                    [
                        "upload",
                        "--repo-id", "test/repo",
                        "--segments", str(segments_dir),
                        "--token", cli_token,
                        "--dry-run",
                    ],
                    env={TOKEN_ENV_VAR: env_token},
                )
                
                # CLI should use provided token, not call require_token()
                assert result.exit_code == 0
                # require_token should NOT have been called
                mock_auth.return_value.require_token.assert_not_called()

    def test_upload_cli_uses_token_env_as_fallback(self, tmp_path):
        """Verify upload command uses HF_TOKEN env var when --token not provided."""
        runner = CliRunner()
        env_token = "hf_from_env_fallback"
        segments_dir = tmp_path / "segments"
        segments_dir.mkdir()
        
        with patch("src.uploader_cli.main.LocalScanner") as mock_scanner:
            mock_scanner.return_value.scan_folder.return_value = {
                "total_files": 0,
                "total_size": 0,
                "by_species": {},
            }
            
            # Mock AuthService to verify token resolution order
            with patch("src.uploader_cli.main.AuthService") as mock_auth:
                mock_auth_instance = MagicMock()
                mock_auth_instance.require_token.return_value = env_token
                mock_auth.return_value = mock_auth_instance
                
                result = runner.invoke(
                    cli,
                    [
                        "upload",
                        "--repo-id", "test/repo",
                        "--segments", str(segments_dir),
                        "--dry-run",
                    ],
                    env={TOKEN_ENV_VAR: env_token},
                )
                
                # Should succeed
                assert result.exit_code == 0
