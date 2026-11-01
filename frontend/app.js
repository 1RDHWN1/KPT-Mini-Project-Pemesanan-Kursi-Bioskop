const seatMap = document.querySelector('#seat-map');
const selectedSeatLabel = document.querySelector('#selected-seat');
const bookButton = document.querySelector('#book-button');
const nameInput = document.querySelector('#customer-name');
const connection = document.querySelector('#connection');
const bookingList = document.querySelector('#booking-list');
const bookingCount = document.querySelector('#booking-count');
const toast = document.querySelector('#toast');

let seats = [];
let selectedSeat = null;
let toastTimer;
const bookingsKey = 'bioskop-kita-bookings';

function localBookings() {
  try { return JSON.parse(localStorage.getItem(bookingsKey) || '[]'); }
  catch { return []; }
}

function saveBookings(bookings) {
  localStorage.setItem(bookingsKey, JSON.stringify(bookings));
  renderBookings();
}

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle('error', isError);
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3200);
}

function renderSeats() {
  seatMap.replaceChildren();
  const rows = [...new Set(seats.map(seat => seat.baris))];
  const heading = document.createElement('div');
  heading.className = 'seat-row seat-heading';
  heading.append(document.createElement('span'));
  for (let number = 1; number <= 10; number++) {
    if (number === 6) {
      const aisle = document.createElement('span');
      aisle.className = 'aisle-space';
      heading.append(aisle);
    }
    const label = document.createElement('span');
    label.className = 'column-label';
    label.textContent = number;
    heading.append(label);
  }
  seatMap.append(heading);
  for (const row of rows) {
    const rowElement = document.createElement('div');
    rowElement.className = 'seat-row';
    const rowLabel = document.createElement('span');
    rowLabel.className = 'row-label';
    rowLabel.textContent = row;
    rowElement.append(rowLabel);
    for (const seat of seats.filter(item => item.baris === row).sort((a, b) => a.nomor - b.nomor)) {
      if (seat.nomor === 6) {
        const aisle = document.createElement('span');
        aisle.className = 'aisle-space';
        aisle.setAttribute('aria-hidden', 'true');
        rowElement.append(aisle);
      }
      const button = document.createElement('button');
      button.className = `seat${seat.tersedia ? '' : ' booked'}${selectedSeat === seat.id ? ' selected' : ''}`;
      button.textContent = seat.nomor;
      button.title = `${seat.id} — ${seat.tersedia ? 'tersedia' : 'terpesan'}`;
      button.setAttribute('aria-label', `Kursi ${seat.id}, ${seat.tersedia ? 'tersedia' : 'terpesan'}`);
      button.disabled = !seat.tersedia;
      button.addEventListener('click', () => {
        selectedSeat = selectedSeat === seat.id ? null : seat.id;
        renderSeats();
        updateSelection();
      });
      rowElement.append(button);
    }
    seatMap.append(rowElement);
  }
  updateSelection();
}

function updateSelection() {
  selectedSeatLabel.textContent = selectedSeat || 'Belum ada';
  bookButton.disabled = !selectedSeat;
}

function renderBookings() {
  const bookings = localBookings();
  bookingCount.textContent = bookings.length;
  bookingList.replaceChildren();
  if (!bookings.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-bookings';
    empty.textContent = 'Belum ada pesanan di perangkat ini.';
    bookingList.append(empty);
    return;
  }
  for (const booking of bookings) {
    const item = document.createElement('div');
    item.className = 'booking-item';
    const label = document.createElement('span');
    label.textContent = `${booking.kursi_id} · ${booking.nama_pemesan}`;
    const cancel = document.createElement('button');
    cancel.textContent = 'Batalkan';
    cancel.addEventListener('click', () => cancelBooking(booking));
    item.append(label, cancel);
    bookingList.append(item);
  }
}

async function loadSeats() {
  try {
    const response = await fetch('/api/seats');
    if (!response.ok) throw new Error('Gagal mengambil status kursi');
    const data = await response.json();
    seats = data.kursi;
    if (selectedSeat && !seats.some(seat => seat.id === selectedSeat && seat.tersedia)) selectedSeat = null;
    renderSeats();
  } catch (error) {
    connection.className = 'connection offline';
    connection.innerHTML = '<span></span> Server tidak terhubung';
  }
}

function connectSeatUpdates() {
  const events = new EventSource('/api/stream');
  events.addEventListener('open', () => {
    connection.className = 'connection online';
    connection.innerHTML = '<span></span> Live';
  });
  events.addEventListener('seats', event => {
    const data = JSON.parse(event.data);
    seats = data.kursi;
    if (selectedSeat && !seats.some(seat => seat.id === selectedSeat && seat.tersedia)) selectedSeat = null;
    renderSeats();
  });
  events.addEventListener('error', () => {
    connection.className = 'connection offline';
    connection.innerHTML = '<span></span> Menyambungkan ulang…';
  });
}

async function bookSelectedSeat() {
  if (!selectedSeat) return;
  const nama = nameInput.value.trim();
  if (!nama) {
    nameInput.focus();
    showToast('Isi nama pemesan dulu ya.', true);
    return;
  }
  bookButton.disabled = true;
  bookButton.textContent = 'Memproses…';
  const payload = { request_id: crypto.randomUUID(), kursi_id: selectedSeat, nama_pemesan: nama };
  try {
    const response = await fetch('/api/book', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Pemesanan gagal. Coba lagi.');
    if (!result.sukses) throw new Error(result.pesan);
    saveBookings([...localBookings(), { booking_id: result.booking_id, kursi_id: result.kursi_id, nama_pemesan: nama }]);
    selectedSeat = null;
    showToast(result.pesan);
    await loadSeats();
  } catch (error) {
    showToast(error.message || 'Pemesanan gagal. Coba lagi.', true);
  } finally {
    bookButton.innerHTML = 'Pesan kursi <span>→</span>';
    updateSelection();
  }
}

async function cancelBooking(booking) {
  try {
    const response = await fetch('/api/cancel', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: crypto.randomUUID(), booking_id: booking.booking_id }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Pembatalan gagal.');
    if (!result.sukses) throw new Error(result.pesan);
    saveBookings(localBookings().filter(item => item.booking_id !== booking.booking_id));
    showToast(result.pesan);
    await loadSeats();
  } catch (error) {
    showToast(error.message || 'Pembatalan gagal.', true);
  }
}

bookButton.addEventListener('click', bookSelectedSeat);
nameInput.addEventListener('input', updateSelection);
renderBookings();
loadSeats();
connectSeatUpdates();
