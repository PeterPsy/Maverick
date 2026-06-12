import { expect, Page, test } from '@playwright/test';

type BackendRequest = Record<string, unknown>;

const baseBootstrap = {
  ok: true,
  leads: [
    { id: 'lead_northwind', name: 'Northwind Expansion', status: 'new', updated_at: '2026-05-20T10:00:00Z', tags: [{ name: 'growth' }] }
  ],
  accounts: [
    { id: 'account_acme', name: 'Acme Corp', status: 'priority', updated_at: '2026-05-21T11:00:00Z', tags: [{ name: 'enterprise' }] }
  ],
  contacts: [
    { id: 'contact_jane', display_name: 'Jane Example', account_id: 'account_acme', email: 'jane@example.com', updated_at: '2026-05-22T12:00:00Z' }
  ],
  deals: [
    {
      id: 'deal_platform',
      name: 'Platform Expansion',
      account_id: 'account_acme',
      contact_id: 'contact_jane',
      stage: 'Discovery',
      stage_id: 'stage_discovery',
      value: 48000,
      currency: 'EUR',
      close_date: '2026-06-15',
      owner_id: 'owner_1',
      created_at: '2026-05-20T09:00:00Z',
      updated_at: '2026-05-23T13:00:00Z'
    }
  ],
  tasks: [
    { id: 'task_followup', subject: 'Follow up with Acme', status: 'open', account_id: 'account_acme', owner_id: 'owner_1', due_at: '2026-05-20T09:00:00Z', updated_at: '2026-05-24T14:00:00Z' }
  ],
  notes: [],
  activities: [],
  pipelines: [{ id: 'pipeline_default', name: 'Default', is_default: 1 }],
  pipeline_stages: [{ id: 'stage_discovery', pipeline_id: 'pipeline_default', name: 'Discovery', position: 1, probability: 0.25 }],
  saved_views: [
    { id: 'priority_accounts', title: 'Priority accounts', entity_type: 'account', filters: { status: 'priority' } }
  ],
  duplicates: {
    ok: true,
    groups: [
      {
        entity_type: 'account',
        field: 'domain',
        value: 'acme.example',
        count: 2,
        records: [
          {
            id: 'account_acme',
            name: 'Acme Corp',
            domain: 'acme.example',
            owner_id: 'owner_1',
            status: 'priority',
            summary: 'Primary account',
            tags: [{ name: 'enterprise' }],
            custom_fields: { segment: 'Strategic' }
          },
          {
            id: 'account_acme_dupe',
            name: 'Acme Duplicate',
            domain: 'acme.example',
            owner_id: 'owner_2',
            status: 'new',
            summary: 'Imported duplicate',
            tags: [{ name: 'imported' }],
            custom_fields: { segment: 'Commercial' }
          }
        ]
      }
    ]
  },
  schema: { custom_fields: [] },
  next_action_suggestions: [
    { kind: 'follow_up', score: 92, reason: 'Open priority account', entity_type: 'account', entity_id: 'account_acme', title: 'Call Acme buyer', record: { id: 'account_acme', name: 'Acme Corp', status: 'priority' } }
  ],
  workflow_proposals: [
    {
      id: 'proposal_renewal',
      status: 'pending',
      entity_type: 'account',
      entity_id: 'account_acme',
      title: 'Create renewal task',
      proposal: { reason: 'Renewal window is open', action: { type: 'create_task', title: 'Renewal check-in' } },
      source: 'automation'
    },
    {
      id: 'proposal_update',
      status: 'approved',
      entity_type: 'deal',
      entity_id: 'deal_platform',
      title: 'Update deal stage',
      proposal: { reason: 'Demo completed', action: { type: 'update_record', entity_type: 'deal', id: 'deal_platform', changes: { stage_id: 'proposal', stage: 'Proposal' } } },
      source: 'assistant'
    },
    {
      id: 'proposal_invalid',
      status: 'approved',
      entity_type: 'account',
      entity_id: 'account_acme',
      title: 'Invalid workflow update',
      proposal: { reason: 'Missing change payload', action: { type: 'update_record', entity_type: 'account', id: 'missing_account', changes: {} } },
      source: 'assistant'
    }
  ],
  counts: { lead: 1, account: 1, contact: 1, deal: 1 },
  view_state: { view_filter: { mode: 'search', query: '', entity_type: 'all', refs: [], title: '' } }
};

function recordsTablePayload(body: BackendRequest) {
  const entityType = String(body.entity_type || 'all');
  const pagination = (body.pagination || {}) as { cursor?: string };
  const cursor = typeof pagination.cursor === 'string' ? pagination.cursor : '';
  const filters = (body.filters || {}) as Record<string, unknown>;
  const isFiltered = filters.status === 'priority';
  const isDealFiltered = filters.status === 'Discovery';
  const accountRow = {
    entity_type: 'account',
    id: 'account_acme',
    title: 'Acme Corp',
    record: baseBootstrap.accounts[0],
    computed: { last_activity_at: '2026-05-24T09:00:00Z' },
    display: { account: 'Acme Corp', contact: 'Jane Example' }
  };
  const dealRow = {
    entity_type: 'deal',
    id: 'deal_platform',
    title: 'Platform Expansion',
    record: baseBootstrap.deals[0],
    computed: { weighted_value: 12000, next_action: 'Schedule demo', last_activity_at: '2026-05-25T09:00:00Z' },
    display: { account: 'Acme Corp', contact: 'Jane Example' }
  };
  const firstPageRows = [
    {
      entity_type: 'lead',
      id: 'lead_northwind',
      title: 'Northwind Expansion',
      record: baseBootstrap.leads[0],
      computed: { next_action: 'Qualify budget', last_activity_at: '2026-05-23T09:00:00Z' },
      display: { account: '', contact: '' }
    },
    accountRow,
    dealRow
  ];
  const secondPageRows = [
    {
      entity_type: 'contact',
      id: 'contact_jane',
      title: 'Sierra Contact',
      record: { ...baseBootstrap.contacts[0], display_name: 'Sierra Contact' },
      computed: { last_activity_at: '2026-05-22T09:00:00Z' },
      display: { account: 'Acme Corp', contact: 'Sierra Contact' }
    }
  ];
  const rows = cursor === 'page-2' ? secondPageRows : isFiltered || entityType === 'account' ? [accountRow] : isDealFiltered || entityType === 'deal' ? [dealRow] : firstPageRows;
  return {
    ok: true,
    records: rows,
    columns: [
      { key: 'type', label: 'Type' },
      { key: 'name', label: 'Name' },
      { key: 'account_id', label: 'Account' },
      { key: 'contact_id', label: 'Contact' },
      { key: 'status_stage', label: 'Status' },
      { key: 'updated', label: 'Updated' },
      { key: 'tags', label: 'Tags' }
    ],
    counts: { lead: 1, account: 1, contact: 1, deal: 1 },
    next_cursor: cursor === 'page-2' || isFiltered || entityType === 'account' ? '' : 'page-2',
    has_more: cursor !== 'page-2' && !isFiltered && entityType !== 'account'
  };
}

function operationsFeedPayload(body: BackendRequest) {
  if (body.owner_id === 'owner_1' && body.due_overdue === true) {
    return {
      ok: true,
      generated_at: '2026-05-26T09:10:00Z',
      counts: { to_do: 1, to_approve: 0, done: 0, discarded: 0, audit: 0 },
      sections: [
        {
          key: 'to_do',
          count: 1,
          items: [
            {
              kind: 'task',
              ref: { entity_type: 'task', entity_id: 'task_followup' },
              status: 'open',
              title: 'Follow up with Acme',
              reason: 'Open CRM task',
              source: 'crm.tasks',
              due_at: '2026-05-20T09:00:00Z',
              updated_at: '2026-05-24T14:00:00Z'
            }
          ]
        },
        { key: 'to_approve', count: 0, items: [] },
        { key: 'done', count: 0, items: [] },
        { key: 'discarded', count: 0, items: [] },
        { key: 'audit', count: 0, items: [] }
      ]
    };
  }
  return {
    ok: true,
    generated_at: '2026-05-26T09:00:00Z',
    counts: { to_do: 3, to_approve: 3, done: 4, discarded: 1, audit: 5 },
    sections: [
      {
        key: 'to_do',
        count: 3,
        items: [
          {
            kind: 'task',
            ref: { entity_type: 'task', entity_id: 'task_followup' },
            status: 'open',
            title: 'Follow up with Acme',
            reason: 'Open CRM task',
            source: 'crm.tasks',
            due_at: '2026-05-20T09:00:00Z',
            updated_at: '2026-05-24T14:00:00Z'
          },
          {
            kind: 'task',
            ref: { entity_type: 'task', entity_id: 'task_followup' },
            status: 'open',
            title: 'Follow up with Acme',
            reason: 'Open CRM task',
            source: 'crm.tasks',
            due_at: '2026-05-20T09:00:00Z',
            updated_at: '2026-05-24T14:00:00Z'
          }
        ]
      },
      {
        key: 'to_approve',
        count: 3,
        items: [
          {
            kind: 'workflow_proposal',
            ref: { entity_type: 'account', entity_id: 'account_acme', proposal_id: 'proposal_renewal' },
            status: 'pending',
            title: 'Create renewal task',
            reason: 'Renewal window is open',
            source: 'automation',
            action_type: 'create_task'
          },
          {
            kind: 'workflow_proposal',
            ref: { entity_type: 'deal', entity_id: 'deal_platform', proposal_id: 'proposal_update' },
            status: 'approved',
            title: 'Update deal stage',
            reason: 'Demo completed',
            source: 'assistant',
            action_type: 'update_record'
          },
          {
            kind: 'workflow_proposal',
            ref: { entity_type: 'account', entity_id: 'account_acme', proposal_id: 'proposal_invalid' },
            status: 'approved',
            title: 'Invalid workflow update',
            reason: 'Missing change payload',
            source: 'assistant',
            action_type: 'update_record'
          }
        ]
      },
      {
        key: 'done',
        count: 4,
        items: [
          {
            kind: 'workflow_proposal',
            ref: { entity_type: 'account', entity_id: 'account_acme', proposal_id: 'proposal_applied' },
            status: 'applied',
            title: 'Applied account enrichment',
            reason: 'Matched company domain',
            source: 'crm.workflow',
            action_type: 'update_record',
            updated_at: '2026-05-25T10:00:00Z'
          }
        ]
      },
      {
        key: 'audit',
        count: 5,
        items: [
          {
            kind: 'audit_event',
            ref: { event_id: 'event_merge', entity_type: 'account', entity_id: 'account_acme' },
            title: 'record.merged',
            reason: 'Duplicate review',
            source: 'crm.audit',
            created_at: '2026-05-25T12:00:00Z'
          }
        ]
      },
      {
        key: 'discarded',
        count: 1,
        items: [
          {
            kind: 'workflow_proposal',
            ref: { entity_type: 'account', entity_id: 'account_acme', proposal_id: 'proposal_rejected' },
            status: 'rejected',
            title: 'Rejected stale task',
            reason: 'Bad fit',
            source: 'automation',
            action_type: 'create_task'
          }
        ]
      }
    ]
  };
}

function workflowProposalPreviewPayload(body: BackendRequest) {
  const id = String(body.id || '');
  if (id === 'proposal_update') {
    return {
      ok: true,
      workflow_proposal: baseBootstrap.workflow_proposals[1],
      preview: {
        proposal_id: 'proposal_update',
        status: 'approved',
        action_type: 'update_record',
        target: { entity_type: 'deal', id: 'deal_platform' },
        changes: [
          { field: 'stage_id', current_value: 'stage_discovery', proposed_value: 'proposal' },
          { field: 'stage', current_value: 'Discovery', proposed_value: 'Proposal' }
        ],
        proposed_task: null,
        validation_issues: [],
        can_approve: true,
        can_apply: true
      }
    };
  }
  if (id === 'proposal_invalid') {
    return {
      ok: true,
      workflow_proposal: baseBootstrap.workflow_proposals[2],
      preview: {
        proposal_id: 'proposal_invalid',
        status: 'approved',
        action_type: 'update_record',
        target: { entity_type: 'account', id: 'missing_account' },
        changes: [],
        proposed_task: null,
        validation_issues: ['update_record target is not active', 'update_record has no applicable changes'],
        can_approve: false,
        can_apply: false
      }
    };
  }
  return {
    ok: true,
    workflow_proposal: baseBootstrap.workflow_proposals[0],
    preview: {
      proposal_id: 'proposal_renewal',
      status: 'pending',
      action_type: 'create_task',
      target: { entity_type: 'account', id: 'account_acme' },
      changes: [],
      proposed_task: { title: 'Renewal check-in', account_id: 'account_acme', priority: 'normal' },
      validation_issues: [],
      can_approve: true,
      can_apply: false
    }
  };
}

function pipelineBoardPayload(dealCount = 1) {
  const deals = Array.from({ length: dealCount }, (_, index) => {
    if (index === 0) return { ...baseBootstrap.deals[0], health: { status: 'active', label: 'Age 3d', is_stuck: false }, account_label: 'Acme Corp', contact_label: 'Jane Example' };
    return {
      ...baseBootstrap.deals[0],
      id: `deal_bulk_${index}`,
      name: `Bulk Pipeline Deal ${index}`,
      value: 1000 + index,
      health: { status: 'active', label: 'Age 1d', is_stuck: false },
      account_label: 'Acme Corp',
      contact_label: 'Jane Example'
    };
  });
  const totalValue = deals.reduce((total, deal) => total + Number(deal.value || 0), 0);
  const weightedValue = deals.reduce((total, deal) => total + Number(deal.value || 0) * 0.25, 0);
  return {
    ok: true,
    pipeline: { id: 'pipeline_default', name: 'Default', is_default: 1 },
    stages: [
      {
        id: 'stage_discovery',
        pipeline_id: 'pipeline_default',
        name: 'Discovery',
        position: 1,
        probability: 0.25,
        deal_count: deals.length,
        totals: { EUR: totalValue },
        weighted: { EUR: weightedValue },
        total_value: totalValue,
        weighted_value: weightedValue,
        deals
      }
    ],
    totals: {
      deal_count: deals.length,
      currency_totals: { EUR: totalValue },
      weighted_currency_totals: { EUR: weightedValue },
      total_value: totalValue,
      weighted_value: weightedValue
    }
  };
}

async function mockCrmBackend(page: Page, options: { pipelineDealCount?: number } = {}) {
  const requests: BackendRequest[] = [];
  await page.route('**/api/apps/crm/backend', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}') as BackendRequest;
    requests.push(body);
    const action = String(body.action || '');
    let payload: unknown = { ok: true };
    if (action === 'bootstrap') {
      payload = baseBootstrap;
    } else if (action === 'crm.records_table') {
      payload = recordsTablePayload(body);
    } else if (action === 'crm.sales_reports') {
      payload = {
        ok: true,
        weighted_forecast: {
          currency_totals: { EUR: 12000, USD: 8000 },
          total_weighted_value: 20000,
          by_stage: [{ stage: 'Discovery', stage_id: 'stage_discovery', deal_count: 1, total_value: 48000, weighted_value: 12000, currency: 'EUR' }]
        },
        lead_conversion: { total: 4, converted: 1, conversion_rate: 0.25, avg_days_to_convert: 6.5 },
        task_overdue: {
          total: 2,
          drilldown_filters: { kind: 'task', status: 'open', due_overdue: 'true' },
          by_owner: [{ owner_id: 'owner_1', task_count: 2, drilldown_filters: { kind: 'task', status: 'open', due_overdue: 'true', owner_id: 'owner_1' } }]
        },
        activities_by_owner: [{ owner_id: 'owner_1', total: 3, by_type: { call: 2, email: 1 }, drilldown_filters: { kind: 'activity', owner_id: 'owner_1' } }],
        pipeline_value_by_stage: [{ stage: 'Discovery', stage_id: 'stage_discovery', deal_count: 1, total_value: 48000, weighted_value: 12000, currency: 'EUR' }],
        deal_aging: [{ id: 'deal_platform', name: 'Platform Expansion', stage: 'Discovery', stage_id: 'stage_discovery', age_days: 3, value: 48000, currency: 'EUR' }]
      };
    } else if (action === 'crm.pipeline_board') {
      payload = pipelineBoardPayload(options.pipelineDealCount || 1);
    } else if (action === 'crm.operations_feed') {
      payload = operationsFeedPayload(body);
    } else if (action === 'crm.workflow_proposal_preview') {
      payload = workflowProposalPreviewPayload(body);
    } else if (action === 'crm.merge_records') {
      payload = {
        ok: true,
        entity_type: body.entity_type,
        target: { id: body.target_id, name: body.target_id === 'account_acme_dupe' ? 'Acme Duplicate' : 'Acme Corp' },
        merged_ids: body.source_ids || [],
        reassigned_counts: {}
      };
    } else if (action === 'crm.timeline') {
      payload = { ok: true, items: [{ id: 'activity_recent', subject: 'Recent call', status: 'done' }] };
    } else if (action === 'crm.external_timeline') {
      payload = { ok: true, items: [] };
    } else if (action === 'crm.list_external_refs') {
      payload = { ok: true, external_refs: [] };
    } else if (action === 'crm.audit_log') {
      payload = { ok: true, events: [] };
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  return requests;
}

function lastRequest(requests: BackendRequest[], action: string) {
  return [...requests].reverse().find((request) => request.action === action);
}

test('routes between CRM cockpit views and opens a legacy record deep link', async ({ page }) => {
  const requests = await mockCrmBackend(page);
  await page.goto('/apps/crm/');
  await expect(page.getByRole('heading', { name: 'CRM records' })).toBeVisible();

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'reports' } }, window.location.origin);
  });
  await expect(page.getByRole('heading', { name: 'Pipeline by stage' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Forecast by currency' })).toBeVisible();
  await expect(page.getByText('EUR 12,000', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Overdue tasks by owner' })).toBeVisible();
  await expect(page.getByRole('button', { name: /owner_1 2 overdue tasks/ })).toBeVisible();
  await expect(page.getByText('call: 2')).toBeVisible();

  await page.getByRole('button', { name: /1 deals/ }).click();
  await expect.poll(() => lastRequest(requests, 'crm.records_table')?.entity_type).toBe('deal');
  await expect.poll(() => (lastRequest(requests, 'crm.records_table')?.filters as Record<string, string> | undefined)?.status).toBe('Discovery');
  await expect(page.getByRole('heading', { name: 'CRM records' })).toBeVisible();

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'reports' } }, window.location.origin);
  });
  await page.getByRole('button', { name: /owner_1/ }).first().click();
  await expect(page.getByRole('heading', { name: 'Agent deck' })).toBeVisible();
  await expect(page.getByText('Discovery')).toBeVisible();
  await expect.poll(() => lastRequest(requests, 'crm.operations_feed')?.owner_id).toBe('owner_1');
  await expect.poll(() => lastRequest(requests, 'crm.operations_feed')?.due_overdue).toBe(true);
  await expect.poll(() => lastRequest(requests, 'crm.operations_feed')?.kind).toBe('task');

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'reports' } }, window.location.origin);
  });
  await page.getByRole('button', { name: /owner_1 3 activities/ }).click();
  await expect(page.getByRole('heading', { name: 'Agent deck' })).toBeVisible();
  await expect.poll(() => lastRequest(requests, 'crm.operations_feed')?.owner_id).toBe('owner_1');
  await expect.poll(() => lastRequest(requests, 'crm.operations_feed')?.kind).toBe('activity');

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'accounts/account_acme' } }, window.location.origin);
  });
  await expect(page.getByLabel('Record type')).toHaveCount(0);
  const detailPanel = page.getByRole('region', { name: 'Acme Corp' });
  await expect(detailPanel).toBeVisible();
  await expect(page.getByRole('heading', { name: 'CRM records' })).toHaveCount(0);
  await expect(detailPanel.getByRole('button', { name: 'Back' })).toBeVisible();
  await expect(detailPanel.getByTitle('More record actions')).toBeVisible();
  await expect(detailPanel.getByRole('button', { name: 'Tag record' })).toHaveCount(0);
  await detailPanel.getByTitle('More record actions').click();
  await expect(detailPanel.getByRole('menuitem', { name: 'Tag record' })).toBeVisible();
  await expect(detailPanel.getByRole('menuitem', { name: 'Archive record' })).toBeVisible();
  await detailPanel.getByText('Manual reference').click();
  await detailPanel.getByRole('textbox', { name: 'Title' }).fill('Intro thread');
  await detailPanel.getByRole('textbox', { name: 'Date' }).fill('2026-05-20');
  await detailPanel.getByRole('textbox', { name: 'Summary' }).fill('Initial conversation');
  await expect(detailPanel.getByRole('button', { name: 'Link' })).toBeDisabled();
  expect(lastRequest(requests, 'crm.link_external_ref')).toBeUndefined();
  await detailPanel.getByRole('button', { name: 'Back' }).click();
  await expect(page.getByRole('heading', { name: 'CRM records' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Filter/ })).toHaveClass(/active/);
});

test('paginates the records table with stable next and previous cursors', async ({ page }) => {
  const requests = await mockCrmBackend(page);
  await page.goto('/apps/crm/');
  await expect(page.getByText('Northwind Expansion')).toBeVisible();

  await page.getByRole('button', { name: 'Next' }).click();
  await expect.poll(() => (lastRequest(requests, 'crm.records_table')?.pagination as { cursor?: string } | undefined)?.cursor).toBe('page-2');
  await expect(page.locator('tbody tr').filter({ hasText: 'Sierra Contact' })).toBeVisible();

  await page.getByRole('button', { name: 'Previous' }).click();
  await expect.poll(() => (lastRequest(requests, 'crm.records_table')?.pagination as { cursor?: string } | undefined)?.cursor).toBe('');
  await expect(page.getByText('Northwind Expansion')).toBeVisible();
});

test('scrolls the lead detail page content vertically', async ({ page }) => {
  await page.setViewportSize({ width: 760, height: 500 });
  await mockCrmBackend(page);
  await page.goto('/apps/crm/');

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'leads/lead_northwind' } }, window.location.origin);
  });

  const detailPanel = page.getByRole('region', { name: 'Northwind Expansion' });
  await expect(detailPanel).toBeVisible();
  const detailContent = detailPanel.locator('.detail-content');
  await expect(detailContent).toBeVisible();
  await expect.poll(() => detailPanel.evaluate((node) => window.getComputedStyle(node).overflowY)).toBe('auto');
  await expect.poll(() => detailPanel.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
  const box = await detailPanel.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.wheel(0, 900);
  await expect.poll(() => detailPanel.evaluate((node) => node.scrollTop > 0)).toBe(true);
});

test('renders the pipeline board with stage totals and deal context', async ({ page }) => {
  const requests = await mockCrmBackend(page);
  page.on('dialog', async (dialog) => {
    await dialog.accept();
  });
  await page.goto('/apps/crm/');

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'pipeline' } }, window.location.origin);
  });

  await expect(page.getByText('1 deal')).toBeVisible();
  const stageTotals = page.getByLabel('Discovery stage totals');
  await expect(stageTotals.getByText('EUR 48,000')).toBeVisible();
  await expect(stageTotals.getByText('EUR 12,000')).toBeVisible();

  const dealCard = page.getByRole('button', { name: /Platform Expansion/ });
  await expect(dealCard).toContainText('Acme Corp / Jane Example');
  await expect(dealCard).toContainText('Close Jun 15, 2026');
  await expect(dealCard).toContainText('Owner owner_1');
  await expect(dealCard).toContainText(/Age|Stuck|Past due/);
  await expect(page.getByTitle('Discovery stage options')).toBeVisible();
  await expect(page.getByRole('menuitem', { name: 'Edit stage' })).toHaveCount(0);
  await page.getByTitle('Discovery stage options').click();
  await expect(page.getByRole('menuitem', { name: 'Edit stage' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: 'Delete stage' })).toBeVisible();
  await page.getByRole('menuitem', { name: 'Delete stage' }).click();
  await expect.poll(() => lastRequest(requests, 'crm.delete_pipeline_stage')?.id).toBe('stage_discovery');
  await expect(page.getByTitle('Pipeline admin actions')).toBeVisible();
  await expect.poll(() => lastRequest(requests, 'crm.pipeline_board')?.action).toBe('crm.pipeline_board');
});

test('loads pipeline board deals from backend beyond bootstrap limits', async ({ page }) => {
  await mockCrmBackend(page, { pipelineDealCount: 105 });
  await page.goto('/apps/crm/');

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'pipeline' } }, window.location.origin);
  });

  await expect(page.getByText('105 deals')).toBeVisible();
  await expect(page.getByRole('button', { name: /Bulk Pipeline Deal 104/ })).toBeVisible();
});

test('applies unified workspace search through backend-backed UI actions', async ({ page }) => {
  const requests = await mockCrmBackend(page);
  const browserDialogs: string[] = [];
  page.on('dialog', async (dialog) => {
    browserDialogs.push(dialog.type());
    await dialog.dismiss();
  });
  await page.goto('/apps/crm/');

  await expect(page.getByPlaceholder('Status or stage')).toHaveCount(0);
  await expect(page.getByText('Saved views')).toHaveCount(0);

  await page.getByLabel('Search CRM').fill('Acme');
  await expect.poll(() => lastRequest(requests, 'crm.records_table')?.query).toBe('Acme');
  await expect.poll(() => lastRequest(requests, 'crm.set_view_filter')?.query).toBe('Acme');
  await expect.poll(() => lastRequest(requests, 'crm.set_view_filter')?.entity_type).toBe('all');
  expect(browserDialogs).toEqual([]);
});

test('runs bulk tag actions from real row selection state', async ({ page }) => {
  const requests = await mockCrmBackend(page);
  const browserDialogs: string[] = [];
  page.on('dialog', async (dialog) => {
    browserDialogs.push(dialog.type());
    await dialog.dismiss();
  });
  await page.goto('/apps/crm/');

  await page.getByLabel('Select Northwind Expansion').check();
  await expect(page.getByText('1 selected')).toBeVisible();
  await page.getByTitle('Bulk actions').click();
  await page.getByRole('menuitem', { name: 'Tag selected records' }).click();
  const bulkTagDialog = page.getByRole('dialog', { name: 'Tag selected records' });
  await expect(bulkTagDialog).toBeVisible();
  await bulkTagDialog.getByRole('textbox', { name: 'Tag' }).fill('enterprise');
  await bulkTagDialog.getByRole('button', { name: 'Apply tag' }).click();

  await expect.poll(() => lastRequest(requests, 'crm.bulk_update')?.tag).toBe('enterprise');
  expect(lastRequest(requests, 'crm.bulk_update')).toMatchObject({
    entity_type: 'lead',
    ids: ['lead_northwind'],
    operation: 'tag'
  });
  expect(browserDialogs).toEqual([]);
});

test('shows agent-centric pipeline deck and workflow actions', async ({ page }) => {
  const requests = await mockCrmBackend(page);
  await page.goto('/apps/crm/');

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'operations' } }, window.location.origin);
  });

  await expect(page.getByRole('heading', { name: 'Agent deck' })).toBeVisible();
  await expect(page.getByText('7 active signals')).toBeVisible();
  const agentSummary = page.getByLabel('Agent deck summary');
  await expect(agentSummary.getByText('Next', { exact: true })).toBeVisible();
  await expect(agentSummary.getByText('Approvals', { exact: true })).toBeVisible();
  await expect(agentSummary.getByText('Duplicates', { exact: true })).toBeVisible();
  await expect(agentSummary.getByText('Audit', { exact: true })).toBeVisible();
  await expect(page.getByText('Discovery')).toBeVisible();
  await expect(page.getByText('Follow up with Acme')).toBeVisible();
  await expect(page.getByText('Follow up with Acme')).toHaveCount(1);
  await expect(page.getByText('Call Acme buyer')).toHaveCount(0);

  await expect(page.getByText('Create renewal task')).toBeVisible();
  await expect(page.getByText(/pending · Account: Acme Corp · Renewal check-in/)).toBeVisible();
  await page.getByRole('button', { name: 'Review Create renewal task' }).click();
  await expect.poll(() => lastRequest(requests, 'crm.workflow_proposal_preview')?.id).toBe('proposal_renewal');
  await expect(page.getByRole('dialog', { name: 'Create renewal task' })).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Create renewal task' }).getByText('Task to create')).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Create renewal task' }).getByText('Renewal check-in')).toBeVisible();
  await page.getByRole('dialog', { name: 'Create renewal task' }).getByRole('button', { name: 'Approve Create renewal task' }).click();
  await expect.poll(() => lastRequest(requests, 'crm.approve_workflow_proposal')?.id).toBe('proposal_renewal');

  await page.getByRole('button', { name: 'Review Update deal stage' }).click();
  await expect.poll(() => lastRequest(requests, 'crm.workflow_proposal_preview')?.id).toBe('proposal_update');
  await expect(page.getByRole('dialog', { name: 'Update deal stage' }).getByText('Fields to change')).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Update deal stage' }).getByText('stage id')).toBeVisible();
  await page.getByRole('dialog', { name: 'Update deal stage' }).getByRole('button', { name: 'Close workflow proposal preview' }).click();

  await expect(page.getByText('acme.example', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Acme Corp acme.example · owner_1 · priority' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Acme Duplicate acme.example · owner_2 · new' })).toBeVisible();
  await page.getByRole('button', { name: 'Review duplicate acme.example' }).click();
  const duplicateDialog = page.getByRole('dialog', { name: 'Merge duplicate records' });
  await expect(duplicateDialog).toBeVisible();
  await expect(duplicateDialog.getByText('owner id')).toBeVisible();
  await expect(duplicateDialog.getByText('Primary account')).toBeVisible();
  await expect(duplicateDialog.getByText('Imported duplicate')).toBeVisible();
  await duplicateDialog.getByLabel('Use Acme Duplicate as target').check();
  await expect(duplicateDialog.getByLabel('Use Acme Corp as source')).toBeChecked();
  await duplicateDialog.getByRole('button', { name: 'Merge duplicate records' }).click();
  await expect.poll(() => lastRequest(requests, 'crm.merge_records')?.target_id).toBe('account_acme_dupe');
  expect(lastRequest(requests, 'crm.merge_records')).toMatchObject({
    entity_type: 'account',
    source_ids: ['account_acme']
  });
  await expect(page.getByText('Merged 1 account source record into Acme Duplicate.')).toBeVisible();
  await expect(page.getByText('No duplicate groups detected.')).toBeVisible();

  await page.evaluate(() => {
    window.postMessage({ type: 'maverick.app.navigate', params: { app_page: 'reports' } }, window.location.origin);
  });
  await expect(page.getByRole('heading', { name: 'Overdue tasks by owner' })).toBeVisible();
  await page.getByRole('button', { name: /owner_1\s+2 overdue tasks/ }).click();
  await expect(page.getByRole('heading', { name: 'Agent deck' })).toBeVisible();
  await expect.poll(() => lastRequest(requests, 'crm.operations_feed')?.owner_id).toBe('owner_1');
  await expect.poll(() => lastRequest(requests, 'crm.operations_feed')?.due_overdue).toBe(true);
  await expect.poll(() => lastRequest(requests, 'crm.operations_feed')?.kind).toBe('task');
});

test('captures desktop and mobile CRM screenshots', async ({ page }, testInfo) => {
  await mockCrmBackend(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/apps/crm/');
  await expect(page.getByRole('heading', { name: 'CRM records' })).toBeVisible();
  const desktop = await page.screenshot({ path: testInfo.outputPath('crm-desktop.png'), fullPage: true });
  expect(desktop.length).toBeGreaterThan(10_000);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'CRM records' })).toBeVisible();
  const mobile = await page.screenshot({ path: testInfo.outputPath('crm-mobile.png'), fullPage: true });
  expect(mobile.length).toBeGreaterThan(10_000);
});
