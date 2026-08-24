import { initialState, reduce } from './state.mjs';

let state = initialState;
const tabs = document.querySelector('#tabs');
const backend = document.querySelector('#backend');
const lease = document.querySelector('#lease');
const evidenceCount = document.querySelector('#evidence-count');

function render() {
  tabs.replaceChildren(...state.tabs.map(tab => {
    const button = document.createElement('button');
    button.className = `tab ${tab.id === state.activeTab ? 'active' : ''}`;
    button.textContent = `${tab.title}${tab.lifecycle === 'terminated' ? ' · crashed' : ''}`;
    button.addEventListener('click', () => dispatch({ kind: 'tab.selected', id: tab.id }));
    return button;
  }));
  backend.textContent = `${state.capability.backend} · ${state.capability.status}`;
  backend.className = `badge ${state.capability.status}`;
  lease.textContent = state.lease.writerId
    ? `writer ${state.lease.writerId} · epoch ${state.lease.epoch}`
    : 'single-writer lease unclaimed';
  evidenceCount.textContent = String(state.evidenceCount);
}

function dispatch(event) { state = reduce(state, event); render(); }
document.querySelector('#takeover').addEventListener('click', () => dispatch({ kind: 'session.created', writerId: 'local-human', epoch: state.lease.epoch + 1 }));
document.querySelector('#observe').addEventListener('click', () => dispatch({ kind: 'evidence.added' }));
document.querySelector('#evidence').addEventListener('click', () => dispatch({ kind: 'evidence.added' }));
render();
