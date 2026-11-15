import React from 'react';

function downloadUrl(value) {
  return typeof value === 'string' && /^\/api\/instructions\/originals\/[A-Za-z0-9_-]+\.pdf$/.test(value) ? value : null;
}

function sourceUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function sha(value) {
  return typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value) ? value.toLowerCase() : null;
}

function date(value) {
  const match = typeof value === 'string' && value.match(/^(\d{4})-(\d{2})-(\d{2})(?:T|$)/);
  return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
}

// These are API-verified originals, separately bound to exact variants. A PDF
// never becomes extracted instruction text or increases its separate coverage.
export function hasMedicationInstructionOriginals(originals) {
  return Array.isArray(originals) && originals.some(document =>
    document?.content_format === 'official_original_pdf'
    && date(document.verification?.verified_at)
    && document.verification?.status === 'verified'
    && Array.isArray(document.matched_variants) && document.matched_variants.length > 0
    && sha(document.original_sha256)
    && downloadUrl(document.download_url),
  );
}

export function visibleMedicationInstructionOriginals(originals, instructions) {
  const inlineBindings = new Map();
  for (const document of Array.isArray(instructions) ? instructions : []) {
    const hash = sha(document?.original_sha256);
    if (!hash || !Array.isArray(document.sections) || !document.sections.some(section => typeof section?.text === 'string' && section.text.trim())) continue;
    inlineBindings.set(hash, [...(inlineBindings.get(hash) || []), ...(Array.isArray(document.bindings) ? document.bindings : [])]);
  }
  return (Array.isArray(originals) ? originals : []).filter(document => {
    if (!hasMedicationInstructionOriginals([document])) return false;
    const bindings = inlineBindings.get(sha(document.original_sha256)) || [];
    // Equal files can have different verified variant scopes. Keep the PDF
    // unless every exact PDF binding is also represented by inline text.
    return !document.matched_variants.every(variant => {
      if (typeof variant?.gtin !== 'string' || !variant.gtin || typeof variant.ru_number !== 'string' || !variant.ru_number) return false;
      return bindings.some(binding => binding?.gtin === variant.gtin && binding.ru_number === variant.ru_number
        && ['form', 'dosage', 'pack_size'].every(key => !variant[key] || binding[key] === variant[key]));
    });
  });
}

export default function MedicationInstructionOriginals({ originals, instructions, coverage }) {
  const documents = visibleMedicationInstructionOriginals(originals, instructions);
  if (!documents.length) return null;
  return (
    <section id="instrukciya-pdf" className="mb-8 md:mb-12 scroll-mt-32" data-testid="med-instruction-originals">
      <div className="rounded-2xl border border-slate-100 bg-white p-5 md:p-8">
        <h2 className="mb-3 text-xl font-bold text-slate-900 md:text-2xl">Официальная инструкция (PDF)</h2>
        <p className="mb-5 text-sm leading-relaxed text-slate-600">Полный документ из официального источника. Таблицы, схемы и все страницы доступны в исходном PDF.</p>
        {coverage?.fully_covered === false && <p className="mb-5 rounded-lg bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-600" data-testid="med-instruction-originals-partial">Официальные PDF подтверждены для {coverage.covered_variants} из {coverage.total_variants} вариантов. Для остальных вариантов оригинал ещё не подтверждён. Сверяйте регистрационный номер, форму выпуска и дозировку.</p>}
        <div className="space-y-6">
          {documents.map((document, index) => {
            const variants = Array.isArray(document.matched_variants) ? document.matched_variants : [];
            const numbers = [...new Set([...(Array.isArray(document.registration_numbers) ? document.registration_numbers : []), ...variants.map(variant => variant.ru_number)].filter(Boolean))];
            const source = sourceUrl(document.source?.url);
            const isLeaflet = document.document_type === 'patient_leaflet';
            return (
              <article key={document.id || document.original_sha256} className={index ? 'border-t border-slate-200 pt-6' : ''} data-testid="med-instruction-original" data-document-type={isLeaflet ? 'patient_leaflet' : 'medical_instruction'}>
                <h3 className="text-lg font-semibold text-slate-900">{isLeaflet ? 'Листок-вкладыш (PDF)' : document.title || 'Инструкция по применению (PDF)'}</h3>
                {isLeaflet && document.title && <p className="mt-1 text-base text-slate-700">{document.title}</p>}
                <dl className="mt-3 space-y-2 text-sm text-slate-600">
                  {numbers.length > 0 && <div><dt className="inline font-medium text-slate-700">Регистрационные номера (РУ): </dt><dd className="inline">{numbers.join(', ')}</dd></div>}
                  {document.source?.name && <div><dt className="inline font-medium text-slate-700">Источник: </dt><dd className="inline">{source ? <a href={source} target="_blank" rel="noopener noreferrer" className="text-emerald-700 hover:underline">{document.source.name}</a> : document.source.name}</dd></div>}
                  {document.version && <div className="break-words"><dt className="inline font-medium text-slate-700">Версия: </dt><dd className="inline">{document.version}</dd></div>}
                  {document.approved_at && <div><dt className="inline font-medium text-slate-700">Дата утверждения: </dt><dd className="inline">{date(document.approved_at)}</dd></div>}
                  {date(document.verification?.verified_at) && <div><dt className="inline font-medium text-slate-700">Проверено: </dt><dd className="inline">{date(document.verification.verified_at)}</dd></div>}
                </dl>
                {variants.length > 0 && <ul className="mt-3 space-y-1 text-xs text-slate-500" aria-label="Варианты препарата по этому PDF">{variants.map((variant, variantIndex) => <li key={`${variant.gtin || variant.ru_number}-${variantIndex}`} className="break-words">{[variant.ru_number ? `РУ: ${variant.ru_number}` : '', variant.gtin ? `GTIN: ${variant.gtin}` : ''].filter(Boolean).join(' · ')}</li>)}</ul>}
                <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm font-medium text-emerald-700">
                  <a href={downloadUrl(document.download_url)} target="_blank" rel="noopener noreferrer" className="hover:underline">Открыть полную инструкцию (PDF)</a>
                  <a href={`${downloadUrl(document.download_url)}?download=true`} download className="hover:underline">Скачать PDF</a>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
