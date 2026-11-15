import React from 'react';

// The API only publishes reviewed documents bound to exact catalogue variants.
// A selected pack label is not an identity: always retain every supplied binding.
export function hasMedicationInstructions(instructions) {
  return Array.isArray(instructions) && instructions.some(document =>
    Array.isArray(document?.sections) && document.sections.some(section =>
      typeof section?.text === 'string' && section.text.trim(),
    ),
  );
}

function externalUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function formatDate(value) {
  if (typeof value !== 'string') return '';
  const date = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:T|$)/);
  return date ? `${date[3]}.${date[2]}.${date[1]}` : value;
}

function InstructionText({ text }) {
  // Render source text, never source HTML. Blank lines and original numbered
  // markers survive, while lists remain accessible to assistive technologies.
  return String(text).replace(/\r\n?/g, '\n').split(/\n\s*\n/).filter(block => block.trim()).map((block, index) => {
    const lines = block.split('\n');
    if (lines.every(line => /^\s*[-–—•*]\s+/.test(line))) {
      return <ul key={index} className="list-disc space-y-1 pl-5">{lines.map((line, lineIndex) => <li key={lineIndex}>{line.replace(/^\s*[-–—•*]\s+/, '')}</li>)}</ul>;
    }
    if (lines.every(line => /^\s*\d+[.)]\s+/.test(line))) {
      return <ol key={index} className="list-none space-y-1">{lines.map((line, lineIndex) => <li key={lineIndex}>{line}</li>)}</ol>;
    }
    return <p key={index} className="whitespace-pre-wrap">{block}</p>;
  });
}

export default function MedicationInstructions({ instructions, coverage }) {
  const documents = Array.isArray(instructions) ? instructions.filter(document => hasMedicationInstructions([document])) : [];
  const partial = documents.length > 0 && coverage?.fully_covered === false;
  return (
    <section id="instrukciya" className="mb-8 md:mb-12 scroll-mt-32" data-testid="med-instructions">
      <div className="rounded-2xl border border-slate-100 bg-white p-5 md:p-8">
        <h2 className="mb-3 text-xl font-bold text-slate-900 md:text-2xl">Инструкция по применению</h2>
        {!documents.length ? (
          <p className="text-sm leading-relaxed text-slate-600" data-testid="med-instructions-pending">Официальная инструкция для вариантов этого препарата ещё не подтверждена.</p>
        ) : (
          <>
            {partial && <p className="mb-5 rounded-lg bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-600" data-testid="med-instructions-partial">Инструкции подтверждены для {coverage.covered_variants} из {coverage.total_variants} вариантов. Для остальных вариантов инструкция ещё не подтверждена. Сверяйте регистрационный номер, форму выпуска и дозировку.</p>}
            <div className="space-y-8">
              {documents.map((document, index) => {
                const isPatientLeaflet = document.document_type === 'patient_leaflet';
                const bindings = Array.isArray(document.bindings) ? document.bindings : [];
                const registrationNumbers = [...new Set([
                  ...(Array.isArray(document.registration_numbers) ? document.registration_numbers : []),
                  ...bindings.map(binding => binding.ru_number),
                ].filter(Boolean))];
                const sourceUrl = externalUrl(document.source?.url);
                const originalUrl = externalUrl(document.original_url);
                return (
                  <article key={document.id || index} className={index ? 'border-t border-slate-200 pt-8' : ''} data-testid="med-instruction-document" data-document-type={isPatientLeaflet ? 'patient_leaflet' : 'medical_instruction'}>
                    <h3 className="text-lg font-semibold text-slate-900">{isPatientLeaflet ? 'Листок-вкладыш' : document.title || 'Инструкция по применению'}{!document.title && registrationNumbers.length > 0 ? ` — ${registrationNumbers.join(', ')}` : ''}</h3>
                    {isPatientLeaflet && document.title && <p className="mt-1 text-base text-slate-700">{document.title}</p>}
                    <dl className="mt-3 space-y-2 text-sm text-slate-600">
                      {registrationNumbers.length > 0 && <div><dt className="inline font-medium text-slate-700">Регистрационные номера (РУ): </dt><dd className="inline">{registrationNumbers.join(', ')}</dd></div>}
                      {document.source?.name && <div><dt className="inline font-medium text-slate-700">Источник: </dt><dd className="inline">{sourceUrl ? <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="text-emerald-700 hover:underline">{document.source.name}</a> : document.source.name}</dd></div>}
                      {document.version && <div><dt className="inline font-medium text-slate-700">Версия: </dt><dd className="inline">{document.version}</dd></div>}
                      {document.approved_at && <div><dt className="inline font-medium text-slate-700">Дата утверждения: </dt><dd className="inline">{formatDate(document.approved_at)}</dd></div>}
                      {document.retrieved_at && <div><dt className="inline font-medium text-slate-700">Дата получения из источника: </dt><dd className="inline">{formatDate(document.retrieved_at)}</dd></div>}
                    </dl>
                    {bindings.length > 0 && (
                      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3" data-testid="med-instruction-bindings">
                        <h4 className="text-sm font-semibold text-slate-900">Варианты препарата по этой инструкции</h4>
                        <ul className="mt-2 space-y-2 text-sm text-slate-700">
                          {bindings.map((binding, bindingIndex) => <li key={`${binding.gtin || binding.ru_number || 'variant'}-${bindingIndex}`}>
                            {[binding.form, binding.dosage, binding.pack_size].filter(Boolean).join(' · ')}
                            {(binding.ru_number || binding.gtin) && <span className="block break-words text-xs text-slate-500">{[binding.ru_number ? `РУ: ${binding.ru_number}` : '', binding.gtin ? `GTIN: ${binding.gtin}` : ''].filter(Boolean).join(' · ')}</span>}
                          </li>)}
                        </ul>
                      </div>
                    )}
                    {originalUrl && <a href={originalUrl} target="_blank" rel="noopener noreferrer" className="mt-4 inline-block text-sm font-medium text-emerald-700 hover:underline">Оригинал инструкции</a>}
                    <div className="mt-6 space-y-6">
                      {document.sections.filter(section => typeof section?.text === 'string' && section.text.trim()).map((section, sectionIndex) => (
                        <div key={`${section.key || 'section'}-${sectionIndex}`}>
                          {section.title && <h4 className="mb-2 text-base font-semibold text-slate-900">{section.title}</h4>}
                          <div className="space-y-3 break-words text-sm leading-relaxed text-slate-700"><InstructionText text={section.text} /></div>
                        </div>
                      ))}
                    </div>
                  </article>
                );
              })}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
