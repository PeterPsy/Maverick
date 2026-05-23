import { Pencil } from 'lucide-react';
import { BootstrapPayload, CrmRecord, PipelineStage } from '../api';
import { money, titleFor } from '../domain/routing';

export function Pipeline({
  data,
  select,
  onMoveDeal,
  onConfigureStage
}: {
  data: BootstrapPayload;
  select: (value: { entity: string; record: CrmRecord }) => void;
  onMoveDeal: (dealId: string, stageId: string) => void;
  onConfigureStage: (stage?: PipelineStage) => void;
}) {
  return (
    <section className="pipeline-board">
      {data.pipeline_stages.map((stage) => (
        <div
          className="pipeline-column"
          key={stage.id}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            const dealId = event.dataTransfer.getData('text/crm-deal-id');
            if (dealId) onMoveDeal(dealId, stage.id);
          }}
        >
          <h2>
            <span>{stage.name}</span>
            <button type="button" onClick={() => onConfigureStage(stage)} aria-label={`Edit ${stage.name} stage`}>
              <Pencil size={14} aria-hidden="true" />
            </button>
          </h2>
          {data.deals
            .filter((deal) => deal.stage_id === stage.id || deal.stage === stage.name)
            .map((deal) => (
              <button
                className="deal-card"
                key={deal.id}
                draggable
                onClick={() => select({ entity: 'deal', record: deal })}
                onDragStart={(event) => event.dataTransfer.setData('text/crm-deal-id', deal.id)}
              >
                <strong>{titleFor(deal)}</strong>
                <span>{money(deal) || 'No value'}</span>
              </button>
            ))}
        </div>
      ))}
      <button className="pipeline-add-stage" type="button" onClick={() => onConfigureStage()}>
        Add stage
      </button>
    </section>
  );
}
