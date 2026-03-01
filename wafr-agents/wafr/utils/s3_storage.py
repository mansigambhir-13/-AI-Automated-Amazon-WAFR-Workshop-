"""
S3 Storage utility for uploading WAFR reports and artifacts.
"""

import os
import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class S3ReportStorage:
    """Handles uploading WAFR reports to S3."""
    
    def __init__(self, bucket_name: Optional[str] = None, region: str = "us-east-1"):
        """
        Initialize S3 storage.
        
        Args:
            bucket_name: S3 bucket name. If None, will try to load from:
                1. S3_BUCKET environment variable
                2. infrastructure_config.json
                3. Hardcoded production bucket as final fallback
            region: AWS region
        """
        self.region = region
        self.bucket_name = bucket_name or self._load_bucket_name()
        
        if not self.bucket_name:
            logger.warning("No S3 bucket configured. S3 uploads will be disabled.")
            self.s3_client = None
        else:
            try:
                import boto3
                self.s3_client = boto3.client('s3', region_name=region)
                logger.info(f"S3 storage initialized with bucket: {self.bucket_name}")
            except Exception as e:
                logger.error(f"Failed to initialize S3 client: {e}")
                self.s3_client = None
    
    def _load_bucket_name(self) -> Optional[str]:
        """
        Load S3 bucket name from multiple sources in order of priority:
        1. S3_BUCKET environment variable
        2. infrastructure_config.json file
        3. Hardcoded production bucket as final fallback
        """
        # Priority 1: Environment variable (used in AgentCore deployment)
        bucket_from_env = os.environ.get("S3_BUCKET")
        if bucket_from_env:
            logger.info(f"Using S3 bucket from environment variable: {bucket_from_env}")
            return bucket_from_env
        
        # Priority 2: Config file
        bucket_from_config = self._load_bucket_from_config()
        if bucket_from_config:
            return bucket_from_config
        
        # Priority 3: Hardcoded production bucket (ensures reports are always stored)
        production_bucket = "wafr-agent-production-artifacts-842387632939"
        logger.info(f"Using hardcoded production S3 bucket: {production_bucket}")
        return production_bucket
    
    def _load_bucket_from_config(self) -> Optional[str]:
        """
        Load S3 bucket name from infrastructure_config.json.
        
        Production bucket: wafr-agent-production-artifacts-842387632939
        See: docs/PRODUCTION_DEVELOPER_PLAN.md for production configuration.
        """
        try:
            # Try multiple paths to find infrastructure_config.json
            # Get the directory where this file is located
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            # Go up: utils -> wafr -> src -> project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file_dir)))
            
            possible_paths = [
                # From project root (calculated from file location)
                os.path.join(project_root, "infrastructure_config.json"),
                # From current working directory (when running from root)
                os.path.join(os.getcwd(), "infrastructure_config.json"),
                # Relative to current file
                os.path.join(current_file_dir, "..", "..", "..", "infrastructure_config.json"),
                # Just the filename (if running from project root)
                "infrastructure_config.json",
            ]
            
            for config_path in possible_paths:
                # Normalize the path
                config_path = os.path.normpath(config_path)
                if os.path.exists(config_path):
                    logger.info(f"Loading S3 config from: {os.path.abspath(config_path)}")
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                        bucket_name = config.get("s3_bucket")
                        if bucket_name:
                            logger.info(f"✅ Found S3 bucket in config: {bucket_name}")
                            logger.info(f"   Production bucket: wafr-agent-production-artifacts-842387632939")
                            return bucket_name
                        else:
                            logger.warning(f"Config file found but 's3_bucket' key is missing or empty")
                    break
            
            logger.warning(f"infrastructure_config.json not found. Searched: {[os.path.abspath(p) if os.path.exists(p) else p for p in possible_paths[:2]]}")
        except Exception as e:
            logger.warning(f"Could not load bucket from config: {e}", exc_info=True)
        return None
    
    def upload_report(
        self,
        file_path: str,
        session_id: str,
        report_type: str = "wafr_report",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Upload a report file to S3.
        
        Args:
            file_path: Local path to the report file
            session_id: Session ID for organizing files
            report_type: Type of report (e.g., "wafr_report", "wa_tool_report")
            metadata: Optional metadata to store as tags
            
        Returns:
            S3 key (path) if successful, None otherwise
        """
        if not self.s3_client or not self.bucket_name:
            logger.warning("S3 not configured, skipping upload")
            return None
        
        if not os.path.exists(file_path):
            logger.error(f"Report file not found: {file_path}")
            return None
        
        try:
            # Generate S3 key: reports/{session_id}/{report_type}_{timestamp}.pdf
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            file_name = os.path.basename(file_path)
            file_ext = os.path.splitext(file_name)[1] or ".pdf"
            
            s3_key = f"reports/{session_id}/{report_type}_{timestamp}{file_ext}"
            
            # Prepare metadata
            extra_args = {
                "ContentType": "application/pdf" if file_ext == ".pdf" else "application/octet-stream",
                "Metadata": {
                    "session_id": session_id,
                    "report_type": report_type,
                    "uploaded_at": datetime.utcnow().isoformat() + "Z",
                }
            }
            
            # Add custom metadata if provided
            if metadata:
                for key, value in metadata.items():
                    if isinstance(value, (str, int, float)):
                        extra_args["Metadata"][f"custom_{key}"] = str(value)
            
            # Upload file
            logger.info(f"Uploading report to S3: s3://{self.bucket_name}/{s3_key}")
            self.s3_client.upload_file(
                file_path,
                self.bucket_name,
                s3_key,
                ExtraArgs=extra_args
            )
            
            s3_uri = f"s3://{self.bucket_name}/{s3_key}"
            logger.info(f"Successfully uploaded report to {s3_uri}")
            
            return s3_key
            
        except Exception as e:
            logger.error(f"Failed to upload report to S3: {e}", exc_info=True)
            return None
    
    def upload_wa_tool_report(
        self,
        file_path: str,
        session_id: str,
        workload_id: Optional[str] = None,
        milestone_number: Optional[int] = None
    ) -> Optional[str]:
        """
        Upload official WA Tool report to S3.
        
        Args:
            file_path: Local path to the WA Tool report
            session_id: Session ID
            workload_id: WA Tool workload ID
            milestone_number: Milestone number
            
        Returns:
            S3 key if successful, None otherwise
        """
        metadata = {}
        if workload_id:
            metadata["workload_id"] = workload_id
        if milestone_number:
            metadata["milestone_number"] = str(milestone_number)
        
        return self.upload_report(
            file_path=file_path,
            session_id=session_id,
            report_type="wa_tool_official_report",
            metadata=metadata
        )
    
    def get_report_url(self, s3_key: str, expires_in: int = 3600) -> Optional[str]:
        """
        Generate a presigned URL for a report.
        
        Args:
            s3_key: S3 key of the report
            expires_in: URL expiration time in seconds (default 1 hour)
            
        Returns:
            Presigned URL or None if error
        """
        if not self.s3_client or not self.bucket_name:
            return None
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expires_in
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None


# Global instance
_s3_storage: Optional[S3ReportStorage] = None


def get_s3_storage() -> S3ReportStorage:
    """Get or create global S3 storage instance."""
    global _s3_storage
    if _s3_storage is None:
        _s3_storage = S3ReportStorage()
    return _s3_storage
