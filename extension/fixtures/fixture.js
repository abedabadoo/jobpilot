window.fixture = { submitted: 0, next: 0, input: 0, changes: 0, controlledValue: '' };
document.querySelector('form').addEventListener('submit', (event) => {
  event.preventDefault();
  window.fixture.submitted++;
});
document.querySelector('#next').addEventListener('click', () => window.fixture.next++);
const first = document.querySelector('#first');
// React-style own value tracker: native prototype setter must be used.
let tracked = '';
Object.defineProperty(first, 'value', {
  get() {
    return Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').get.call(this);
  },
  set(value) {
    tracked = value;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(this, value);
  },
});
first.addEventListener('input', () => {
  if (tracked !== first.value) {
    window.fixture.controlledValue = first.value;
    window.fixture.input++;
    tracked = first.value;
  }
});
document.addEventListener('change', () => window.fixture.changes++);
document.querySelector('#shadow').attachShadow({ mode: 'open' }).innerHTML =
  '<label>City<input id="city"></label>';
