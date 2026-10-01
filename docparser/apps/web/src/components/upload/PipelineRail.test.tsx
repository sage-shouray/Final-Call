import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { PipelineRail } from './PipelineRail';
import type { DocumentPipeline } from '@/types';

/**
 * The rail is where the product's claim is visible: the route is settled about a
 * second in, while extraction still has sixteen seconds to run. These tests hold
 * that reading — and cover the unhappy paths, which is where an interface
 * usually strands people.
 */

function renderRail(pipeline: DocumentPipeline | null, opts: { extracted?: boolean; failed?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PipelineRail pipeline={pipeline} extracted={opts.extracted ?? false} failed={opts.failed ?? false} />
    </QueryClientProvider>,
  );
}

const routed: DocumentPipeline = {
  identity: {
    po_number: '4500022705', invoice_no: 'INV-4500022705',
    elapsed_ms: 37.4, text_chars: 2141, has_text_layer: true,
    po_candidates: ['4500022705'],
  },
  routing: {
    route: 'miro_direct', tcode: 'MIRO', reason: 'SES confirmed on all lines — ready to invoice.',
    resolved: true, po_number: '4500022705', elapsed_ms: 729.7, invoice_subtype: 'service_po',
    confirmation: {
      lines: [{ po_item: '00010', kind: 'SES', confirmed: true, documents: ['0100000683'], gr_expected: 'Open' }],
      missing: [], all_confirmed: true,
    },
  },
};

describe('PipelineRail', () => {
  it('renders nothing when there is no pipeline', () => {
    const { container } = renderRail(null);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the elapsed time of each stage', () => {
    renderRail(routed);
    // Sub-second values stay in milliseconds; seconds only above 1000 ms.
    expect(screen.getByText('37 ms')).toBeInTheDocument();
    expect(screen.getByText('730 ms')).toBeInTheDocument();
  });

  it('switches to seconds once a stage passes a second', () => {
    renderRail({ ...routed, routing: { ...routed.routing!, elapsed_ms: 3948.6 } });
    expect(screen.getByText('3.9 s')).toBeInTheDocument();
  });

  it('names the destination and the document type', () => {
    renderRail(routed);
    expect(screen.getByText('Invoice → MIRO')).toBeInTheDocument();
    expect(screen.getByText('Service PO')).toBeInTheDocument();
  });

  it('shows the evidence behind the routing, not only the verdict', () => {
    // Being able to check the reasoning is what makes removing the manual
    // picker defensible.
    renderRail(routed);
    expect(screen.getByText(/SES 0100000683/)).toBeInTheDocument();
  });

  it('says routing is settled while extraction is still running', () => {
    renderRail(routed, { extracted: false });
    expect(screen.getByText(/routing above is already settled/i)).toBeInTheDocument();
  });

  it('explains a scanned PDF instead of appearing stuck', () => {
    renderRail({
      ...routed,
      identity: { ...routed.identity!, has_text_layer: false, po_number: '', po_candidates: [] },
    });
    expect(screen.getByText(/Scanned PDF/i)).toBeInTheDocument();
  });

  it('tells the user a transient outage needs nothing from them', () => {
    renderRail({
      routing: {
        route: 'hold', tcode: '', reason: 'Could not reach SAP.', resolved: false,
        po_number: '', elapsed_ms: 6000, invoice_subtype: '', retryable: true,
      },
    });
    expect(screen.getByText(/resolves once SAP is reachable/i)).toBeInTheDocument();
  });

  it('lists the checks that failed and stays quiet about the ones that passed', () => {
    renderRail({
      ...routed,
      autopost: {
        decision: 'manual_approval_required', summary: 'Needs approval before posting.',
        enabled: true, auto_post: false, route: 'miro_direct', failed_gates: ['not_duplicate'],
        gates: [
          { gate: 'vendor_match', passed: true, detail: 'GSTIN matches the PO.' },
          { gate: 'not_duplicate', passed: false, detail: 'Invoice already processed as DOC-2026-316316.' },
        ],
      },
    }, { extracted: true });

    expect(screen.getByText(/already processed as DOC-2026-316316/)).toBeInTheDocument();
    expect(screen.getByText('GSTIN matches the PO.')).toBeInTheDocument();
  });

  it.each([
    ['miro_direct',    'Invoice → MIRO'],
    ['migo_then_miro', 'Goods receipt → then MIRO'],
    ['fb60',           'Non-PO → FB60'],
    ['hold',           'Needs attention'],
  ] as const)('labels the %s route as %s', (route, label) => {
    renderRail({
      routing: {
        route, tcode: '', reason: 'x', resolved: route !== 'hold',
        po_number: '', elapsed_ms: 100, invoice_subtype: '',
      },
    });
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
