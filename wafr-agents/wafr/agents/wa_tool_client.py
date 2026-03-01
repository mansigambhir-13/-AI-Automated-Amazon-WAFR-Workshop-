"""
AWS Well-Architected Tool API Client
Provides programmatic access to WA Tool for autonomous WAFR operations
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from wafr.agents.lens_manager import LENS_ARNS

logger = logging.getLogger(__name__)


class WellArchitectedToolClient:
    """Client for interacting with AWS Well-Architected Tool API."""
    
    def __init__(self, region: str = 'us-east-1'):
        """
        Initialize WA Tool client with optimized connection pool.
        
        Args:
            region: AWS region (default: us-east-1)
        """
        self.region = region
        
        # Configure boto3 client with larger connection pool and adaptive retries
        config = Config(
            max_pool_connections=50,  # Increase from default 10 to handle parallel batch processing
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'  # Adaptive retry mode for better handling
            },
            connect_timeout=60,
            read_timeout=120  # Increased read timeout
        )
        
        self.client = boto3.client('wellarchitected', region_name=region, config=config)
        self._review_owner = None  # Cache for review owner

    @staticmethod
    def _convert_lens_aliases_to_arns(lenses: List[str]) -> List[str]:
        """
        Convert lens aliases to full ARNs.
        AWS requires ARNs for lens specification.

        Args:
            lenses: List of lens aliases (e.g., ['wellarchitected', 'genai'])

        Returns:
            List of lens ARNs (e.g., ['arn:aws:wellarchitected::aws:lens/wellarchitected', ...])
        """
        lens_arns = []
        for lens in lenses:
            # If already an ARN, use as-is
            if lens.startswith('arn:'):
                lens_arns.append(lens)
            # Otherwise convert alias to ARN
            elif lens in LENS_ARNS:
                lens_arns.append(LENS_ARNS[lens])
            else:
                # Unknown lens - try to construct ARN assuming it's a valid alias
                logger.warning(f"Unknown lens '{lens}', constructing ARN assuming valid AWS lens alias")
                lens_arns.append(f"arn:aws:wellarchitected::aws:lens/{lens}")

        return lens_arns

    def _get_review_owner(self) -> str:
        """
        Get the review owner email from AWS credentials.
        
        Returns:
            Email address of the current AWS user
        """
        if self._review_owner:
            return self._review_owner
        
        try:
            # Try to get current user identity
            sts_client = boto3.client('sts', region_name=self.region)
            identity = sts_client.get_caller_identity()
            arn = identity.get('Arn', '')
            
            # Extract email from ARN or use account ID
            # ARN format: arn:aws:iam::account-id:user/username
            if 'user/' in arn:
                username = arn.split('user/')[-1]
                # If it looks like an email, use it; otherwise construct one
                if '@' in username:
                    self._review_owner = username
                else:
                    # Use account ID as fallback (will need manual update)
                    account_id = identity.get('Account', 'unknown')
                    self._review_owner = f"wafr-{account_id}@aws.local"
            else:
                # For roles, use account ID
                account_id = identity.get('Account', 'unknown')
                self._review_owner = f"wafr-{account_id}@aws.local"
            
            logger.info(f"Using ReviewOwner: {self._review_owner}")
            return self._review_owner
            
        except Exception as e:
            logger.warning(f"Could not determine review owner from AWS identity: {e}")
            # Fallback to a default
            self._review_owner = "wafr-automation@aws.local"
            return self._review_owner
    
    def create_workload(
        self,
        workload_name: str,
        description: str,
        environment: str = 'PRODUCTION',
        aws_regions: Optional[List[str]] = None,
        lenses: Optional[List[str]] = None,
        review_owner: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Create a new workload in WA Tool.
        
        Args:
            workload_name: Name of the workload
            description: Description of the workload
            environment: Environment type (PRODUCTION, PREPRODUCTION, DEVELOPMENT)
            aws_regions: List of AWS regions
            lenses: List of lens aliases (e.g., ['wellarchitected', 'genai'])
            review_owner: Email of the review owner (if not provided, will be auto-detected)
            tags: Tags for the workload
            
        Returns:
            Workload creation response
        """
        try:
            # Normalize environment value - AWS only accepts PRODUCTION or PREPRODUCTION
            environment_map = {
                'PROD': 'PRODUCTION',
                'PRD': 'PRODUCTION',
                'PRODUCTION': 'PRODUCTION',
                'PREPROD': 'PREPRODUCTION',
                'PRE-PROD': 'PREPRODUCTION',
                'PREPRODUCTION': 'PREPRODUCTION',
                'DEV': 'PREPRODUCTION',  # Map DEV to PREPRODUCTION
                'DEVELOPMENT': 'PREPRODUCTION',
                'TEST': 'PREPRODUCTION',
                'TESTING': 'PREPRODUCTION',
                'STAGE': 'PREPRODUCTION',
                'STAGING': 'PREPRODUCTION',
            }
            
            original_env = environment
            environment = environment_map.get(environment.upper(), 'PRODUCTION')
            
            if original_env.upper() != environment:
                logger.info(f"Normalized environment: '{original_env}' -> '{environment}'")
            # Normalize lens aliases
            from wafr.agents.lens_manager import LensManager
            
            if not lenses:
                lenses = ['wellarchitected']  # Default: just wellarchitected
            else:
                # Normalize all lens aliases
                normalized_lenses = []
                for lens in lenses:
                    normalized = LensManager.normalize_lens_alias(lens)
                    if normalized not in normalized_lenses:
                        normalized_lenses.append(normalized)
                lenses = normalized_lenses
                
                # Ensure wellarchitected is always included
                if 'wellarchitected' not in lenses:
                    lenses = ['wellarchitected'] + lenses
            
            if not aws_regions:
                aws_regions = [self.region]
            
            # ReviewOwner is required - get it if not provided
            if not review_owner:
                review_owner = self._get_review_owner()
            
            # Convert lens aliases to ARNs (AWS requires ARNs)
            lens_arns = self._convert_lens_aliases_to_arns(lenses)
            logger.info(f"Converted {len(lenses)} lens aliases to ARNs: {list(zip(lenses, lens_arns))}")

            params = {
                'WorkloadName': workload_name,
                'Description': description,
                'Environment': environment,
                'AwsRegions': aws_regions,
                'Lenses': lens_arns,  # Use ARNs instead of aliases!
                'ReviewOwner': review_owner,  # Required parameter
                'ClientRequestToken': f"wafr-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            }
            
            if tags:
                params['Tags'] = tags
            
            try:
                response = self.client.create_workload(**params)
                logger.info(f"Created workload: {workload_name} (ID: {response.get('WorkloadId')}) with lenses: {lenses}")
                return response
            except ClientError as e:
                # Handle lens access errors gracefully
                error_code = e.response.get('Error', {}).get('Code', '')
                error_message = e.response.get('Error', {}).get('Message', '')
                
                # Check if it's a lens access error
                if error_code == 'ValidationException' and ('not authorized' in error_message.lower() or 'Failed to get lenses' in error_message):
                    # Show full AWS error details for debugging
                    error_details = {
                        'ErrorCode': error_code,
                        'ErrorMessage': error_message,
                        'RequestId': e.response.get('ResponseMetadata', {}).get('RequestId', 'N/A'),
                        'HTTPStatusCode': e.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 'N/A'),
                        'FullResponse': str(e.response)
                    }
                    logger.warning(f"Lens access error - Full AWS Error Details:")
                    logger.warning(f"  Error Code: {error_details['ErrorCode']}")
                    logger.warning(f"  Error Message: {error_details['ErrorMessage']}")
                    logger.warning(f"  Request ID: {error_details['RequestId']}")
                    logger.warning(f"  HTTP Status: {error_details['HTTPStatusCode']}")
                    logger.debug(f"  Full Response: {error_details['FullResponse']}")

                    # Try to identify which lens failed
                    failed_lenses = []
                    for lens in lenses:
                        if lens.lower() in error_message.lower():
                            failed_lenses.append(lens)
                    
                    # Remove failed lenses and retry
                    working_lenses = [l for l in lenses if l not in failed_lenses]
                    
                    if not working_lenses:
                        # If all lenses failed, use wellarchitected as fallback
                        working_lenses = ['wellarchitected']
                        logger.warning(f"All requested lenses failed. Fallback to wellarchitected. Originally requested: {lenses}")
                    else:
                        logger.info(f"Retrying workload creation with {len(working_lenses)}/{len(lenses)} accessible lenses")
                        logger.info(f"  ✓ Accessible: {working_lenses}")
                        logger.info(f"  ✗ Removed due to access error: {failed_lenses}")
                    
                    # Retry with working lenses only
                    working_lens_arns = self._convert_lens_aliases_to_arns(working_lenses)
                    params['Lenses'] = working_lens_arns
                    params['ClientRequestToken'] = f"wafr-{datetime.now().strftime('%Y%m%d%H%M%S')}"  # New token for retry
                    
                    response = self.client.create_workload(**params)
                    logger.info(f"Created workload: {workload_name} (ID: {response.get('WorkloadId')}) with lenses: {working_lenses}")
                    
                    # Try to associate failed lenses post-creation using associate_lenses API
                    # This works even when create_workload with multiple lenses fails
                    workload_id = response.get('WorkloadId')
                    recovered_lenses = []
                    still_failed = []

                    if workload_id and failed_lenses:
                        logger.info(f"Attempting to associate {len(failed_lenses)} failed lenses via associate_lenses API...")
                        assoc_result = self.associate_lenses(workload_id, failed_lenses)
                        recovered_lenses = assoc_result.get('associated', [])
                        still_failed = [f['lens'] for f in assoc_result.get('failed', [])]

                        if recovered_lenses:
                            logger.info(f"Successfully recovered {len(recovered_lenses)} lenses via associate_lenses: {recovered_lenses}")
                        if still_failed:
                            logger.warning(f"Could not recover {len(still_failed)} lenses: {still_failed}")

                    # Add metadata about lens resolution
                    response['_metadata'] = {
                        'requested_lenses': lenses,
                        'create_workload_lenses': working_lenses,
                        'recovered_via_associate': recovered_lenses,
                        'final_failed_lenses': still_failed,
                        'all_active_lenses': working_lenses + recovered_lenses,
                    }

                    return response
                else:
                    # Re-raise if it's a different error
                    raise
            
        except ClientError as e:
            logger.error(f"Error creating workload: {str(e)}")
            raise
    
    def associate_lenses(
        self,
        workload_id: str,
        lenses: List[str]
    ) -> Dict[str, Any]:
        """
        Associate additional lenses with an existing workload.
        Uses the associate_lenses API which works even when create_workload
        with multiple lenses fails from service-assumed roles.

        Args:
            workload_id: Workload ID
            lenses: List of lens aliases or ARNs to associate

        Returns:
            Dict with 'associated' and 'failed' lens lists
        """
        result = {'associated': [], 'failed': []}

        for lens in lenses:
            lens_arn = self._convert_lens_aliases_to_arns([lens])[0]
            try:
                self.client.associate_lenses(
                    WorkloadId=workload_id,
                    LensAliases=[lens_arn]
                )
                logger.info(f"Associated lens '{lens}' ({lens_arn}) with workload {workload_id}")
                result['associated'].append(lens)
            except ClientError as e:
                error_msg = e.response.get('Error', {}).get('Message', str(e))
                logger.warning(f"Failed to associate lens '{lens}' with workload {workload_id}: {error_msg}")
                result['failed'].append({'lens': lens, 'error': error_msg})

        return result

    def disassociate_lenses(
        self,
        workload_id: str,
        lenses: List[str]
    ) -> Dict[str, Any]:
        """
        Remove lenses from a workload.

        Args:
            workload_id: Workload ID
            lenses: List of lens aliases or ARNs to remove

        Returns:
            Dict with 'removed' and 'failed' lens lists
        """
        result = {'removed': [], 'failed': []}

        for lens in lenses:
            lens_arn = self._convert_lens_aliases_to_arns([lens])[0]
            try:
                self.client.disassociate_lenses(
                    WorkloadId=workload_id,
                    LensAliases=[lens_arn]
                )
                logger.info(f"Disassociated lens '{lens}' from workload {workload_id}")
                result['removed'].append(lens)
            except ClientError as e:
                error_msg = e.response.get('Error', {}).get('Message', str(e))
                logger.warning(f"Failed to disassociate lens '{lens}': {error_msg}")
                result['failed'].append({'lens': lens, 'error': error_msg})

        return result

    def get_workload(self, workload_id: str) -> Dict[str, Any]:
        """Get workload details."""
        try:
            response = self.client.get_workload(WorkloadId=workload_id)
            return response
        except ClientError as e:
            logger.error(f"Error getting workload: {str(e)}")
            raise
    
    def list_workloads(self) -> List[Dict[str, Any]]:
        """List all workloads."""
        try:
            workloads = []
            # Try direct call first (list_workloads doesn't support pagination)
            response = self.client.list_workloads()
            workloads = response.get('WorkloadSummaries', [])
            return workloads
        except ClientError as e:
            logger.error(f"Error listing workloads: {str(e)}")
            return []
    
    def create_milestone(
        self,
        workload_id: str,
        milestone_name: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 5.0
    ) -> Dict[str, Any]:
        """
        Create a milestone for a workload with retry logic for conflicts.
        
        Args:
            workload_id: Workload ID
            milestone_name: Optional milestone name (default: timestamp-based)
            max_retries: Maximum number of retries for ConflictException (default: 3)
            retry_delay: Initial delay between retries in seconds (default: 5.0)
            
        Returns:
            Milestone creation response
        """
        import time
        
        if not milestone_name:
            milestone_name = f"Review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.client.create_milestone(
                    WorkloadId=workload_id,
                    MilestoneName=milestone_name
                )
                logger.info(f"Created milestone: {milestone_name} for workload {workload_id}")
                return response
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                
                # Retry on ConflictException (workload locked by another user/process)
                if error_code == 'ConflictException' and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        f"Workload {workload_id} is locked (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    last_error = e
                    continue
                
                # For other errors or final retry, log and raise
                logger.error(f"Error creating milestone: {str(e)}")
                raise
        
        # If we exhausted all retries
        if last_error:
            logger.error(
                f"Failed to create milestone after {max_retries} attempts. "
                f"Workload may be locked by another user."
            )
            raise last_error
    
    def get_answer(
        self,
        workload_id: str,
        lens_alias: str,
        question_id: str,
        milestone_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get answer for a specific question.

        Args:
            workload_id: Workload ID
            lens_alias: Lens alias or ARN (e.g., 'wellarchitected')
            question_id: Question ID (e.g., 'OPS_01')
            milestone_number: Optional milestone number

        Returns:
            Answer details
        """
        try:
            # Convert lens alias to ARN (required since workload was created with ARNs)
            lens_arn = self._convert_lens_aliases_to_arns([lens_alias])[0]

            params = {
                'WorkloadId': workload_id,
                'LensAlias': lens_arn,  # Use ARN instead of alias
                'QuestionId': question_id
            }

            if milestone_number:
                params['MilestoneNumber'] = milestone_number

            response = self.client.get_answer(**params)
            return response

        except ClientError as e:
            logger.error(f"Error getting answer: {str(e)}")
            raise
    
    def update_answer(
        self,
        workload_id: str,
        lens_alias: str,
        question_id: str,
        selected_choices: List[str],
        notes: Optional[str] = None,
        is_applicable: bool = True,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update answer for a question.

        Args:
            workload_id: Workload ID
            lens_alias: Lens alias or ARN
            question_id: Question ID
            selected_choices: List of selected choice IDs
            notes: Optional notes
            is_applicable: Whether question is applicable
            reason: Optional reason for not applicable

        Returns:
            Update response
        """
        try:
            # Convert lens alias to ARN (required since workload was created with ARNs)
            lens_arn = self._convert_lens_aliases_to_arns([lens_alias])[0]

            params = {
                'WorkloadId': workload_id,
                'LensAlias': lens_arn,  # Use ARN instead of alias
                'QuestionId': question_id,
                'SelectedChoices': selected_choices
            }

            if notes:
                params['Notes'] = notes

            if not is_applicable:
                params['IsApplicable'] = False
                if reason:
                    params['Reason'] = reason

            response = self.client.update_answer(**params)
            logger.info(f"Updated answer for {question_id} in workload {workload_id}")
            return response

        except ClientError as e:
            logger.error(f"Error updating answer: {str(e)}")
            raise
    
    def list_answers(
        self,
        workload_id: str,
        lens_alias: str,
        milestone_number: Optional[int] = None,
        pillar_id: Optional[str] = None,
        question_priority: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all answers for a workload.

        Args:
            workload_id: Workload ID
            lens_alias: Lens alias or ARN
            milestone_number: Optional milestone number
            pillar_id: Optional pillar filter
            question_priority: Optional priority filter

        Returns:
            List of answers
        """
        try:
            # Convert lens alias to ARN (required since workload was created with ARNs)
            lens_arn = self._convert_lens_aliases_to_arns([lens_alias])[0]

            params = {
                'WorkloadId': workload_id,
                'LensAlias': lens_arn  # Use ARN instead of alias
            }

            if milestone_number:
                params['MilestoneNumber'] = milestone_number
            if pillar_id:
                params['PillarId'] = pillar_id
            if question_priority:
                params['QuestionPriority'] = question_priority

            # list_answers doesn't support pagination, call directly
            response = self.client.list_answers(**params)
            answers = response.get('AnswerSummaries', [])
            
            return answers
            
        except ClientError as e:
            logger.error(f"Error listing answers: {str(e)}")
            return []
    
    def get_lens_review(
        self,
        workload_id: str,
        lens_alias: str,
        milestone_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get lens review for a workload.

        Args:
            workload_id: Workload ID
            lens_alias: Lens alias or ARN
            milestone_number: Optional milestone number

        Returns:
            Lens review details
        """
        try:
            # Convert lens alias to ARN (required since workload was created with ARNs)
            lens_arn = self._convert_lens_aliases_to_arns([lens_alias])[0]

            params = {
                'WorkloadId': workload_id,
                'LensAlias': lens_arn  # Use ARN instead of alias
            }

            if milestone_number:
                params['MilestoneNumber'] = milestone_number

            response = self.client.get_lens_review(**params)
            return response

        except ClientError as e:
            logger.error(f"Error getting lens review: {str(e)}")
            raise
    
    def get_lens_review_report(
        self,
        workload_id: str,
        lens_alias: str,
        milestone_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get lens review report (official AWS WAFR PDF).

        Args:
            workload_id: Workload ID
            lens_alias: Lens alias or ARN
            milestone_number: Optional milestone number

        Returns:
            Review report with Base64-encoded PDF
        """
        try:
            # Convert lens alias to ARN (required since workload was created with ARNs)
            lens_arn = self._convert_lens_aliases_to_arns([lens_alias])[0]

            params = {
                'WorkloadId': workload_id,
                'LensAlias': lens_arn  # Use ARN instead of alias
            }

            if milestone_number:
                params['MilestoneNumber'] = milestone_number

            response = self.client.get_lens_review_report(**params)
            return response

        except ClientError as e:
            logger.error(f"Error getting lens review report: {str(e)}")
            raise
    
    def list_lens_review_improvements(
        self,
        workload_id: str,
        lens_alias: str,
        pillar_id: Optional[str] = None,
        milestone_number: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        List improvement items (HRIs and MRIs) for a workload.

        Args:
            workload_id: Workload ID
            lens_alias: Lens alias or ARN
            pillar_id: Optional pillar filter
            milestone_number: Optional milestone number

        Returns:
            List of improvement summaries
        """
        try:
            # Convert lens alias to ARN (required since workload was created with ARNs)
            lens_arn = self._convert_lens_aliases_to_arns([lens_alias])[0]

            params = {
                'WorkloadId': workload_id,
                'LensAlias': lens_arn  # Use ARN instead of alias
            }

            if pillar_id:
                params['PillarId'] = pillar_id
            if milestone_number:
                params['MilestoneNumber'] = milestone_number

            improvements = []
            paginator = self.client.get_paginator('list_lens_review_improvements')

            for page in paginator.paginate(**params):
                improvements.extend(page.get('ImprovementSummaries', []))
            
            return improvements
            
        except ClientError as e:
            logger.error(f"Error listing improvements: {str(e)}")
            return []
    
    def get_consolidated_report(
        self,
        workload_ids: List[str],
        format: str = 'PDF'
    ) -> Dict[str, Any]:
        """
        Get consolidated report for multiple workloads.
        
        Args:
            workload_ids: List of workload IDs
            format: Report format (PDF, JSON)
            
        Returns:
            Consolidated report
        """
        try:
            response = self.client.get_consolidated_report(
                WorkloadIds=workload_ids,
                Format=format
            )
            return response
            
        except ClientError as e:
            logger.error(f"Error getting consolidated report: {str(e)}")
            raise
    
    def list_lenses(self) -> List[Dict[str, Any]]:
        """List available lenses."""
        try:
            lenses = []
            # Try direct call first (list_lenses doesn't support pagination)
            response = self.client.list_lenses()
            lenses = response.get('LensSummaries', [])
            return lenses
        except ClientError as e:
            logger.error(f"Error listing lenses: {str(e)}")
            return []
    
    def get_lens(self, lens_alias: str, lens_version: Optional[str] = None) -> Dict[str, Any]:
        """
        Get lens details.

        Args:
            lens_alias: Lens alias or ARN
            lens_version: Optional lens version

        Returns:
            Lens details
        """
        try:
            # Convert lens alias to ARN for consistency
            lens_arn = self._convert_lens_aliases_to_arns([lens_alias])[0]

            params = {'LensAlias': lens_arn}  # Use ARN instead of alias
            if lens_version:
                params['LensVersion'] = lens_version
            
            response = self.client.get_lens(**params)
            return response
            
        except ClientError as e:
            logger.error(f"Error getting lens: {str(e)}")
            raise
    
    def update_workload(
        self,
        workload_id: str,
        workload_name: Optional[str] = None,
        description: Optional[str] = None,
        environment: Optional[str] = None,
        aws_regions: Optional[List[str]] = None,
        review_owner: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update workload details.
        
        Args:
            workload_id: Workload ID
            workload_name: Optional new name
            description: Optional new description
            environment: Optional new environment
            aws_regions: Optional new regions
            review_owner: Optional new review owner
            
        Returns:
            Update response
        """
        try:
            params = {'WorkloadId': workload_id}
            
            if workload_name:
                params['WorkloadName'] = workload_name
            if description:
                params['Description'] = description
            if environment:
                params['Environment'] = environment
            if aws_regions:
                params['AwsRegions'] = aws_regions
            if review_owner:
                params['ReviewOwner'] = review_owner
            
            response = self.client.update_workload(**params)
            logger.info(f"Updated workload: {workload_id}")
            return response
            
        except ClientError as e:
            logger.error(f"Error updating workload: {str(e)}")
            raise
    
    def delete_workload(self, workload_id: str) -> None:
        """Delete a workload."""
        try:
            self.client.delete_workload(
                WorkloadId=workload_id,
                ClientRequestToken=str(datetime.now().timestamp())
            )
            logger.info(f"Deleted workload: {workload_id}")
        except ClientError as e:
            logger.error(f"Error deleting workload: {str(e)}")
            raise

