import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional
import structlog

from config import config

logger = structlog.get_logger()


class EACompiler:
    """Compiles MQL5 source files and deploys .ex5 to all terminals."""

    METAQUOTES_DIR = Path(
        os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal")
    )

    def compile(self, mq5_path: str) -> Optional[str]:
        """Compile a single .mq5 file to .ex5.

        Returns path to compiled .ex5 or None on failure.
        """
        mq5 = Path(mq5_path)
        if not mq5.exists():
            logger.error("mq5_not_found", path=mq5_path)
            return None

        ex5 = mq5.with_suffix(".ex5")
        metaeditor = config.metaeditor_path

        if not Path(metaeditor).exists():
            logger.error("metaeditor_not_found", path=metaeditor)
            return None

        cmd = [metaeditor, f"/compile:{mq5_path}", f"/log"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.error("compilation_failed",
                           path=mq5_path, code=result.returncode)
                return None
        except Exception as e:
            logger.error("compilation_error", error=str(e))
            return None

        if not ex5.exists():
            logger.error("ex5_not_created", path=str(ex5))
            return None

        logger.info("compilation_success", mq5=mq5.name, ex5=str(ex5))
        return str(ex5)

    def compile_all(self, source_dir: str) -> List[str]:
        """Compile all .mq5 files in directory."""
        compiled: List[str] = []
        for mq5 in Path(source_dir).rglob("*.mq5"):
            ex5 = self.compile(str(mq5))
            if ex5:
                compiled.append(ex5)
        logger.info("compile_all_complete", compiled=len(compiled))
        return compiled

    def deploy(self, ex5_path: str) -> List[str]:
        """Deploy .ex5 to all terminal Expert directories."""
        deployed: List[str] = []
        if not self.METAQUOTES_DIR.exists():
            logger.error("metaquotes_dir_not_found")
            return deployed

        for terminal_id in os.listdir(self.METAQUOTES_DIR):
            experts_dir = self.METAQUOTES_DIR / terminal_id / "MQL5" / "Experts"
            if not experts_dir.exists():
                continue

            dest = experts_dir / Path(ex5_path).name
            try:
                shutil.copy2(ex5_path, dest)
                deployed.append(str(dest))
                logger.info("deployed", terminal=terminal_id, file=dest.name)
            except Exception as e:
                logger.error("deploy_failed", terminal=terminal_id, error=str(e))

        return deployed

    def compile_and_deploy(self, source_dir: str) -> List[str]:
        """Compile all and deploy to all terminals."""
        compiled = self.compile_all(source_dir)
        all_deployed: List[str] = []
        for ex5 in compiled:
            deployed = self.deploy(ex5)
            all_deployed.extend(deployed)
        return all_deployed
