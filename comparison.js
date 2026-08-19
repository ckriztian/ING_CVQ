(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ComparisonEngine = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function normalizeSectorName(value) {
    return String(value || '').trim().toLowerCase().normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ');
  }

  function totalPersonnel(personal) {
    if (!personal || !Array.isArray(personal.tramos)) return null;
    return personal.tramos.reduce((sum, item) => sum + Number(item.personas), 0);
  }

  function numericDelta(a, b) {
    if (a === null || a === undefined || b === null || b === undefined) return null;
    const left = Number(a), right = Number(b);
    return Number.isFinite(left) && Number.isFinite(right) ? right - left : null;
  }

  function alignPersonnel(personalA, personalB) {
    const rows = new Map();
    function add(personal, side) {
      if (!personal || !Array.isArray(personal.tramos)) return;
      personal.tramos.forEach(item => {
        const key = normalizeSectorName(item.nombre);
        if (!rows.has(key)) rows.set(key, {key, name: String(item.nombre).trim(), a: null, b: null});
        const row = rows.get(key);
        row[side] = Number(item.personas);
        if (side === 'a') row.name = String(item.nombre).trim();
      });
    }
    add(personalA, 'a'); add(personalB, 'b');
    return [...rows.values()].map(row => ({...row, delta: numericDelta(row.a, row.b), equal: row.a !== null && row.b !== null && row.a === row.b}));
  }

  function dataComparability(summaryA, summaryB) {
    const domains = ['palletizacion', 'specs', 'personal', 'layout', 'tiempos'];
    return Object.fromEntries(domains.map(domain => {
      const a = summaryA.data_status[domain], b = summaryB.data_status[domain];
      let state = 'missing';
      if (a === 'warning' || b === 'warning') state = a === 'missing' || b === 'missing' ? 'partial' : 'warning';
      else if (a === 'available' && b === 'available') state = 'available';
      else if (a === 'available' || b === 'available') state = 'partial';
      return [domain, {state, a, b}];
    }));
  }

  function validatePersonnelRows(rows) {
    const names = new Set();
    for (const row of rows || []) {
      const name = String(row.nombre || '').trim();
      const people = Number(row.personas);
      if (!name) return {valid:false, error:'Todos los sectores deben tener nombre.'};
      if (!Number.isInteger(people) || people < 0) return {valid:false, error:`La dotación de ${name} debe ser un entero igual o mayor que cero.`};
      const key = name.toLowerCase();
      if (names.has(key)) return {valid:false, error:`El sector ${name} está duplicado.`};
      names.add(key);
    }
    return {valid:true, error:null};
  }

  return {normalizeSectorName, totalPersonnel, numericDelta, alignPersonnel, dataComparability, validatePersonnelRows};
});
