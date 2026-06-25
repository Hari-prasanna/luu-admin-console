"""
Docker container lifecycle management for Sektor Pilot worker instances.

Handles starting, pausing, stopping, and status checking of sector containers.
Per Clean Code Chapter 3: micro-functions (< 25 lines) with structured return types.
Per Clean Code Chapter 7: typed exceptions — no bare except blocks.
"""

import subprocess
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from pathlib import Path

from backend.exceptions import DockerExecutionError
from backend.config import Constants

logger = logging.getLogger(__name__)


# ─── Domain Models ───


class ContainerState:
    """Enumeration of container lifecycle states."""

    RUNNING = "RUNNING"
    IDLE = "IDLE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass
class DockerCommandResult:
    """Structured result from a Docker subprocess command."""

    return_code: int
    standard_output: str
    standard_error: str

    def is_success(self) -> bool:
        """Return True if command exited with return code 0."""
        return self.return_code == 0


# ─── State File Repository ───


class StateFileRepository:
    """Persists container state across process restarts via JSON files."""

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        """
        Initialize with the directory for state files.

        Args:
            state_dir: Directory path for state files (default: ./state/)
        """
        self.state_dir = state_dir or (Path(__file__).parent / "state")
        self.state_dir.mkdir(exist_ok=True)

    def _get_state_file_path(self, sector_id: str) -> Path:
        """Return path to the state file for a given sector."""
        return self.state_dir / f"{sector_id}.state.json"

    def _build_default_state(self, sector_id: str) -> Dict[str, Any]:
        """Build a default (stopped) state dict for a new sector."""
        return {
            "sector_id": sector_id,
            "container_id": None,
            "state": ContainerState.STOPPED,
            "started_at": None,
            "paused_at": None,
        }

    def load(self, sector_id: str) -> Dict[str, Any]:
        """
        Load saved state for a sector, returning default state if file absent.

        Args:
            sector_id: Sector identifier

        Returns:
            State dict with sector_id, container_id, state, started_at, paused_at
        """
        state_file_path = self._get_state_file_path(sector_id)
        if not state_file_path.exists():
            return self._build_default_state(sector_id)

        try:
            with open(state_file_path, "r") as state_file_stream:
                return json.load(state_file_stream)
        except (json.JSONDecodeError, OSError) as file_read_failure:
            logger.error(
                "failed_to_load_sector_state",
                extra={"sector_id": sector_id, "error": str(file_read_failure)},
            )
            return {"sector_id": sector_id, "state": ContainerState.ERROR}

    def save(self, sector_id: str, state_to_persist: Dict[str, Any]) -> None:
        """
        Persist state for a sector to disk.

        Args:
            sector_id: Sector identifier
            state_to_persist: State dict to write
        """
        state_file_path = self._get_state_file_path(sector_id)
        try:
            with open(state_file_path, "w") as state_file_stream:
                json.dump(state_to_persist, state_file_stream, indent=2)
        except OSError as file_write_failure:
            logger.error(
                "failed_to_save_sector_state",
                extra={"sector_id": sector_id, "error": str(file_write_failure)},
            )


# ─── Docker Command Executor ───


class DockerCommandExecutor:
    """Executes Docker CLI commands with timeout and typed error handling."""

    DEFAULT_TIMEOUT_SECONDS = 10

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        """
        Initialize with a command timeout.

        Args:
            timeout_seconds: Max seconds to wait for any Docker command
        """
        self.timeout_seconds = timeout_seconds

    def execute(self, docker_command: List[str]) -> DockerCommandResult:
        """
        Execute a Docker command and return structured result.

        Args:
            docker_command: List of command tokens (e.g., ['docker', 'ps', '-a'])

        Returns:
            DockerCommandResult with return_code, standard_output, standard_error

        Raises:
            DockerExecutionError: If command times out or system error occurs
        """
        try:
            completed_process = subprocess.run(
                docker_command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            return DockerCommandResult(
                return_code=completed_process.returncode,
                standard_output=completed_process.stdout.strip(),
                standard_error=completed_process.stderr.strip(),
            )
        except subprocess.TimeoutExpired as timeout_failure:
            raise DockerExecutionError(
                f"Docker command timed out after {self.timeout_seconds}s",
                context={"command": docker_command},
            ) from timeout_failure
        except OSError as system_call_failure:
            raise DockerExecutionError(
                "Docker command could not be executed (OS error)",
                context={"command": docker_command, "error": str(system_call_failure)},
            ) from system_call_failure


# ─── Container Manager ───


class ContainerManager:
    """Manages Docker container lifecycle for all Sektor Pilot worker sectors."""

    def __init__(self, container_image: str = "sektor-auto-pilot:latest") -> None:
        """
        Initialize with Docker image name.

        Args:
            container_image: Docker image name:tag to run for each worker
        """
        self.container_image = container_image
        self._state_repo = StateFileRepository()
        self._docker_executor = DockerCommandExecutor(
            timeout_seconds=Constants.DOCKER_COMMAND_TIMEOUT_SECONDS
        )

    def _get_container_name(self, sector_id: str) -> str:
        """Return standardized container name for a sector."""
        return f"sektor-pilot-{sector_id}"

    def _container_exists(self, container_name: str) -> bool:
        """
        Check whether a Docker container exists (running or stopped).

        Args:
            container_name: Docker container name

        Returns:
            True if container appears in `docker ps -a`, False otherwise
        """
        try:
            check_result = self._docker_executor.execute([
                "docker", "ps", "-a",
                "--filter", f"name={container_name}",
                "--format", "{{.ID}}",
            ])
            return check_result.is_success() and len(check_result.standard_output) > 0
        except DockerExecutionError:
            return False

    def _container_is_running(self, container_name: str) -> bool:
        """
        Check whether a Docker container is currently running.

        Args:
            container_name: Docker container name

        Returns:
            True if container is in running state, False otherwise
        """
        try:
            check_result = self._docker_executor.execute([
                "docker", "ps",
                "--filter", f"name={container_name}",
                "--format", "{{.ID}}",
            ])
            return check_result.is_success() and len(check_result.standard_output) > 0
        except DockerExecutionError:
            return False

    def _remove_stopped_container(self, container_name: str) -> None:
        """
        Remove an existing stopped container to allow a clean restart.

        Ignores removal failures — a fresh `docker run` will handle the conflict.

        Args:
            container_name: Name of the stopped container to remove
        """
        logger.info("removing_stopped_container", extra={"container_name": container_name})
        try:
            self._docker_executor.execute(["docker", "rm", container_name])
        except DockerExecutionError:
            pass  # Non-fatal: docker run will fail with a clearer error if needed

    def _build_docker_run_command(
        self,
        container_name: str,
        sector_id: str,
        oracle_env_path: str,
    ) -> List[str]:
        """
        Build the `docker run` command for launching a sector worker.

        Args:
            container_name: Docker container name to assign
            sector_id: Sector identifier (passed as SECTOR_ID env var)
            oracle_env_path: Path to oracle.env file for --env-file flag

        Returns:
            List of command tokens ready for subprocess
        """
        import json
        from pathlib import Path

        creds_content = ""
        try:
            creds_path = Path("/app/service_account.json")
            if creds_path.is_file():
                with open(creds_path) as f:
                    creds_content = f.read()
        except Exception:
            pass

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--env-file", oracle_env_path,
            "-e", f"SECTOR_ID={sector_id}",
        ]

        if creds_content:
            cmd.extend(["-e", f"GOOGLE_SHEETS_CREDENTIALS={creds_content}"])

        cmd.append(self.container_image)
        return cmd

    def _record_container_started(
        self,
        sector_id: str,
        container_name: str,
        short_container_id: str,
    ) -> None:
        """
        Persist RUNNING state after a successful `docker run`.

        Args:
            sector_id: Sector identifier
            container_name: Docker container name (for logging)
            short_container_id: First 12 chars of container ID from docker run output
        """
        saved_state = self._state_repo.load(sector_id)
        saved_state["container_id"] = short_container_id
        saved_state["state"] = ContainerState.RUNNING
        saved_state["started_at"] = time.time()
        self._state_repo.save(sector_id, saved_state)
        logger.info(
            "container_started",
            extra={"container_name": container_name, "container_id": short_container_id},
        )

    def _record_container_start_failed(self, sector_id: str) -> None:
        """
        Persist ERROR state after a failed `docker run`.

        Args:
            sector_id: Sector identifier
        """
        saved_state = self._state_repo.load(sector_id)
        saved_state["state"] = ContainerState.ERROR
        self._state_repo.save(sector_id, saved_state)

    def _prepare_container_slot(self, container_name: str) -> None:
        """
        Ensure a clean slot exists for a new container with the given name.

        If a stopped container with that name exists, removes it.
        If the container is running, this method is a no-op (caller checks first).

        Args:
            container_name: Docker container name to clean up
        """
        if self._container_exists(container_name):
            self._remove_stopped_container(container_name)

    def _execute_docker_run(
        self,
        sector_id: str,
        container_name: str,
        oracle_env_path: str,
    ) -> Dict[str, Any]:
        """
        Run `docker run` and return a result dict reflecting success or failure.

        Args:
            sector_id: Sector identifier (for state persistence on failure)
            container_name: Docker container name to create
            oracle_env_path: Path to oracle.env for --env-file

        Returns:
            Dict with success, state, message (and container_id on success)
        """
        docker_run_command = self._build_docker_run_command(
            container_name, sector_id, oracle_env_path
        )
        logger.info("starting_container", extra={"container_name": container_name, "image": self.container_image})
        run_result = self._docker_executor.execute(docker_run_command)

        if not run_result.is_success():
            logger.error("failed_to_start_container", extra={"sector_id": sector_id, "error": run_result.standard_error})
            self._record_container_start_failed(sector_id)
            return {"success": False, "state": ContainerState.ERROR, "message": Constants.ERROR_DOCKER_EXECUTION_FAILED}

        short_container_id = run_result.standard_output[:12]
        self._record_container_started(sector_id, container_name, short_container_id)
        return {"success": True, "state": ContainerState.RUNNING, "message": f"Container {container_name} started", "container_id": short_container_id}

    def start(self, sector_id: str, oracle_env_path: str = "oracle.env") -> Dict[str, Any]:
        """
        Start a Docker container for the specified sector.

        If already running, returns success immediately.
        Removes any pre-existing stopped container before starting fresh.

        Args:
            sector_id: Sector identifier
            oracle_env_path: Path to oracle.env file

        Returns:
            Dict with success (bool), state (str), message (str), container_id (str|None)
        """
        container_name = self._get_container_name(sector_id)

        if self._container_is_running(container_name):
            logger.info("container_already_running", extra={"container_name": container_name})
            return {"success": True, "state": ContainerState.RUNNING, "message": f"Container {container_name} already running"}

        self._prepare_container_slot(container_name)
        return self._execute_docker_run(sector_id, container_name, oracle_env_path)

    def _create_pause_signal_in_container(self, container_name: str) -> None:
        """
        Create .pause file inside running container to signal the worker to suspend.

        Args:
            container_name: Docker container name

        Raises:
            DockerExecutionError: If docker exec command fails
        """
        exec_result = self._docker_executor.execute([
            "docker", "exec", container_name, "touch", "/app/.pause"
        ])
        if not exec_result.is_success():
            raise DockerExecutionError(
                f"Failed to create pause signal in container {container_name}",
                context={"container_name": container_name, "error": exec_result.standard_error},
            )

    def _record_container_paused(self, sector_id: str) -> None:
        """
        Persist PAUSED state after successful pause signal creation.

        Args:
            sector_id: Sector identifier
        """
        saved_state = self._state_repo.load(sector_id)
        saved_state["state"] = ContainerState.PAUSED
        saved_state["paused_at"] = time.time()
        self._state_repo.save(sector_id, saved_state)

    def _send_pause_signal(self, sector_id: str, container_name: str) -> Dict[str, Any]:
        """
        Create pause signal in running container and persist PAUSED state.

        Args:
            sector_id: Sector identifier
            container_name: Docker container name

        Returns:
            Dict with success, state, message
        """
        try:
            self._create_pause_signal_in_container(container_name)
        except DockerExecutionError as pause_signal_failure:
            logger.error("failed_to_pause_container", extra={"sector_id": sector_id, "error": str(pause_signal_failure)})
            return {"success": False, "state": ContainerState.ERROR, "message": Constants.ERROR_DOCKER_EXECUTION_FAILED}
        self._record_container_paused(sector_id)
        logger.info("container_paused", extra={"container_name": container_name})
        return {"success": True, "state": ContainerState.PAUSED, "message": f"Container {container_name} paused"}

    def pause(self, sector_id: str) -> Dict[str, Any]:
        """
        Pause a running worker by creating a pause signal file in the container.

        The worker monitors this file and suspends polling without terminating.

        Args:
            sector_id: Sector identifier

        Returns:
            Dict with success (bool), state (str), message (str)
        """
        container_name = self._get_container_name(sector_id)
        if not self._container_is_running(container_name):
            logger.warning("cannot_pause_stopped_container", extra={"container_name": container_name})
            return {"success": False, "state": ContainerState.STOPPED, "message": f"Container {container_name} not running"}
        return self._send_pause_signal(sector_id, container_name)

    def _stop_container_gracefully(self, container_name: str) -> None:
        """
        Issue `docker stop` with a 15-second grace period.

        Args:
            container_name: Docker container name

        Raises:
            DockerExecutionError: If stop command fails
        """
        stop_result = self._docker_executor.execute([
            "docker", "stop", "-t", "15", container_name
        ])
        if not stop_result.is_success():
            raise DockerExecutionError(
                f"docker stop failed for {container_name}",
                context={"container_name": container_name, "error": stop_result.standard_error},
            )

    def _remove_container(self, container_name: str) -> None:
        """
        Remove a stopped container (non-fatal on failure).

        Args:
            container_name: Docker container name
        """
        try:
            self._docker_executor.execute(["docker", "rm", container_name])
        except DockerExecutionError as remove_failure:
            logger.warning(
                "failed_to_remove_container",
                extra={"container_name": container_name, "error": str(remove_failure)},
            )

    def _record_container_stopped(self, sector_id: str) -> None:
        """
        Persist STOPPED state and clear container ID after stop.

        Args:
            sector_id: Sector identifier
        """
        saved_state = self._state_repo.load(sector_id)
        saved_state["state"] = ContainerState.STOPPED
        saved_state["container_id"] = None
        self._state_repo.save(sector_id, saved_state)

    def _stop_and_remove_container(
        self,
        sector_id: str,
        container_name: str,
    ) -> Dict[str, Any]:
        """
        Issue docker stop + docker rm for a container that is known to exist.

        Args:
            sector_id: Sector identifier (for state persistence and logging)
            container_name: Docker container name

        Returns:
            Dict with success, state, message
        """
        try:
            logger.info("stopping_container", extra={"container_name": container_name})
            self._stop_container_gracefully(container_name)
        except DockerExecutionError as stop_failure:
            logger.error("failed_to_stop_container", extra={"sector_id": sector_id, "error": str(stop_failure)})
            return {"success": False, "state": ContainerState.ERROR, "message": Constants.ERROR_DOCKER_EXECUTION_FAILED}

        logger.info("removing_container", extra={"container_name": container_name})
        self._remove_container(container_name)
        self._record_container_stopped(sector_id)
        logger.info("container_stopped", extra={"container_name": container_name})
        return {"success": True, "state": ContainerState.STOPPED, "message": f"Container {container_name} stopped"}

    def stop(self, sector_id: str) -> Dict[str, Any]:
        """
        Gracefully stop and remove a Docker container.

        Args:
            sector_id: Sector identifier

        Returns:
            Dict with success (bool), state (str), message (str)
        """
        container_name = self._get_container_name(sector_id)

        if not self._container_exists(container_name):
            logger.info("container_does_not_exist", extra={"container_name": container_name})
            self._record_container_stopped(sector_id)
            return {"success": True, "state": ContainerState.STOPPED, "message": f"Container {container_name} not found"}

        return self._stop_and_remove_container(sector_id, container_name)

    def _resolve_actual_container_state(self, container_name: str) -> str:
        """
        Determine actual container state by querying Docker directly.

        Args:
            container_name: Docker container name

        Returns:
            One of ContainerState.RUNNING, IDLE, or STOPPED
        """
        if self._container_is_running(container_name):
            return ContainerState.RUNNING
        if self._container_exists(container_name):
            return ContainerState.IDLE
        return ContainerState.STOPPED

    def _sync_saved_state_if_drifted(
        self,
        sector_id: str,
        saved_state: Dict[str, Any],
        actual_container_state: str,
    ) -> None:
        """
        Update persisted state if Docker reality diverged from saved state.

        Args:
            sector_id: Sector identifier
            saved_state: Currently persisted state dict
            actual_container_state: State resolved from Docker
        """
        if actual_container_state != saved_state.get("state"):
            saved_state["state"] = actual_container_state
            self._state_repo.save(sector_id, saved_state)

    def get_status(self, sector_id: str) -> Dict[str, Any]:
        """
        Get current status of a sector container, verifying against Docker reality.

        Args:
            sector_id: Sector identifier

        Returns:
            Dict with sector_id, container_name, state, container_id, started_at, paused_at
        """
        container_name = self._get_container_name(sector_id)
        saved_state = self._state_repo.load(sector_id)
        actual_container_state = self._resolve_actual_container_state(container_name)
        self._sync_saved_state_if_drifted(sector_id, saved_state, actual_container_state)

        return {
            "sector_id": sector_id,
            "container_name": container_name,
            "state": actual_container_state,
            "container_id": saved_state.get("container_id"),
            "started_at": saved_state.get("started_at"),
            "paused_at": saved_state.get("paused_at"),
        }

    def get_all_status(self) -> List[Dict[str, Any]]:
        """
        Get status of all registered sector containers.

        Returns:
            List of status dicts, one per sector instance
        """
        from backend.automation.sektor_pilot.sector_config import SECTOR_INSTANCES

        return [self.get_status(sector_id) for sector_id in SECTOR_INSTANCES.keys()]
