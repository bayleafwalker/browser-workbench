export const initialState = Object.freeze({
  tabs: [{ id: 'page-1', title: 'New tab', lifecycle: 'open', generation: 1 }],
  activeTab: 'page-1',
  lease: { writerId: null, epoch: 0, mode: 'single-writer' },
  capability: { backend: 'disconnected', status: 'blocked' },
  evidenceCount: 0
});

export function reduce(state, event) {
  if (event.kind === 'session.created') {
    return { ...state, lease: { ...state.lease, writerId: event.writerId, epoch: event.epoch } };
  }
  if (event.kind === 'tab.opened') {
    if (state.tabs.some(tab => tab.id === event.tab.id)) return state;
    return { ...state, tabs: [...state.tabs, event.tab], activeTab: event.tab.id };
  }
  if (event.kind === 'tab.selected' && state.tabs.some(tab => tab.id === event.id)) {
    return { ...state, activeTab: event.id };
  }
  if (event.kind === 'page.terminated') {
    return { ...state, tabs: state.tabs.map(tab => tab.id === event.id ? { ...tab, lifecycle: 'terminated' } : tab) };
  }
  if (event.kind === 'capability.report') {
    return { ...state, capability: { backend: event.backend, status: event.status } };
  }
  if (event.kind === 'evidence.added') return { ...state, evidenceCount: state.evidenceCount + 1 };
  return state;
}

export function canMutate(state, clientId) {
  return Boolean(clientId && state.lease.writerId === clientId);
}
