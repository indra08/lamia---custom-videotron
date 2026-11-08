(function (root, factory) {
  const helpers = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
  else root.VistaraForm = helpers;
})(globalThis, function () {
  const fields = {
    'company.legal_name': ['company', 'Nama perusahaan'],
    'company.npwp': ['npwp', 'NPWP'],
    'company.address': ['address', 'Alamat perusahaan'],
    'contact.full_name': ['pic', 'Nama penanggung jawab'],
    'contact.email': ['email', 'Email'],
    'contact.phone': ['phone', 'Nomor ponsel'],
    'schedule.start_at': ['start', 'Mulai tayang'],
    'schedule.end_at': ['end', 'Selesai tayang'],
    'consent': ['consent', 'Persetujuan'],
  };
  function npwpError(value) {
    const raw = String(value || '').trim();
    if (!raw) return 'NPWP wajib diisi.';
    if (!/^[0-9 .-]+$/.test(raw)) return 'NPWP hanya boleh berisi angka, titik, spasi, atau tanda hubung.';
    const count = raw.replace(/\D/g, '').length;
    return count === 15 || count === 16 ? '' : `NPWP harus 15 atau 16 digit; saat ini ${count} digit.`;
  }
  function apiError(data) {
    const errors = {};
    if (typeof data.detail === 'string') return {message: data.detail, fields: errors};
    if (!Array.isArray(data.detail)) return {message: 'Permintaan gagal. Periksa isian Anda dan coba lagi.', fields: errors};
    const messages = data.detail.map(issue => {
      const key = (issue.loc || []).filter(part => part !== 'body').join('.');
      const [field, label] = fields[key] || ['', 'Isian'];
      let message;
      if (field === 'npwp') message = npwpError(issue.input) || 'Periksa kembali NPWP Anda.';
      else if (issue.type === 'missing') message = `${label} wajib diisi.`;
      else if (issue.type === 'string_too_short') message = `${label} minimal ${issue.ctx?.min_length || 1} karakter.`;
      else if (issue.type === 'string_too_long') message = `${label} maksimal ${issue.ctx?.max_length} karakter.`;
      else message = `${label} tidak valid. Periksa kembali isian Anda.`;
      if (field) errors[field] = message;
      return message;
    });
    return {message: [...new Set(messages)].join(' '), fields: errors};
  }
  return {npwpError, apiError};
});
