"""Explicit anonymous CRM authority; new backend actions are private by default."""
from errors import CrmError
from service import handle_action

READS = set('''bootstrap schema search records_table get_record pipeline_board
    workspace_view overview extension_schema list_extension_records record_context
    timeline audit_log sales_reports filter_records find_duplicates list_custom_fields
    intelligent_next_actions list_workflow_proposals workflow_proposal_preview
    list_external_refs external_timeline list_next_actions operations_feed
    summarize_account account_brief export list_saved_views list_automation_rules
    integration_context integration_get integration_list import_jobs'''.split())
WRITES = set('''create_lead update_lead convert_lead create_account update_account
    create_contact update_contact create_deal update_deal move_deal create_pipeline
    update_pipeline create_pipeline_stage update_pipeline_stage delete_pipeline_stage
    log_activity create_task update_task create_note update_note archive_record
    unarchive_record delete_record tag_record untag_record bulk_update merge_records
    create_extension_record update_extension_record link_records unlink_records
    define_custom_field archive_custom_field set_custom_fields record_enrichment
    propose_workflows approve_workflow_proposal dismiss_workflow_proposal
    reject_workflow_proposal apply_workflow_proposal create_automation_rule
    update_automation_rule run_automation_rules save_view delete_saved_view
    import_plan import_apply'''.split())


class PublicDenied(CrmError):
    code = 'public_action_forbidden'
    status_code = 403


def execute(root, body, *, access):
    if not isinstance(body, dict) or not isinstance(body.get('action'), str):
        raise PublicDenied('An explicit CRM action is required.')
    if any(key.startswith('_') for key in body):
        raise PublicDenied('Private request context is not accepted.')
    action = body['action'].removeprefix('crm.')
    if action not in READS and action not in WRITES:
        raise PublicDenied('This operation is available only inside Maverick, not on the public CRM.')
    if action in WRITES and access != 'read-write':
        raise PublicDenied('The public CRM is read-only. Changes are disabled by its administrator.')
    if action in {'import_plan', 'import_apply'}:
        source = body.get('source')
        if not isinstance(source, dict) or source.get('format', 'json') not in {'csv', 'json', 'versy'}:
            raise PublicDenied('Full backup restore, including integration authority, is private to Maverick.')
    if action in {'approve_workflow_proposal', 'dismiss_workflow_proposal', 'reject_workflow_proposal', 'apply_workflow_proposal'}:
        _, preview = handle_action(root, 'crm.workflow_proposal_preview', {'id': body.get('id')})
        if preview['preview']['action_type'] == 'provider_operation':
            raise PublicDenied('Integration proposals can only be reviewed inside Maverick.')
    canonical = 'crm.' + action
    code, result = handle_action(root, canonical, {**body, 'action': canonical})
    # Public visitors never inherit the owner's shared private view selection.
    if action == 'bootstrap':
        result['view_state'] = {}
    if any(key in result for key in ('dependency_backend_requests', 'core_requests', 'secret_requests')):
        raise PublicDenied('Private integration dispatch is unavailable on the public CRM.')
    return code, result
