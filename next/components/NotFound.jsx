import React from 'react';
import { Link } from 'react-router-dom';
import { Pill, Home as HomeIcon } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-16 md:py-24 text-center">
      <div className="w-20 h-20 mx-auto bg-emerald-50 rounded-2xl flex items-center justify-center mb-6">
        <Pill className="w-10 h-10 text-emerald-600" />
      </div>
      <h1 className="text-4xl md:text-5xl font-extrabold text-slate-900 mb-3">404</h1>
      <p className="text-base md:text-lg text-slate-600 mb-6">Страница не найдена. Возможно, она была перемещена или удалена.</p>
      <Link to="/" className="inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-5 py-2.5 rounded-lg transition">
        <HomeIcon className="w-4 h-4" /> Вернуться на главную
      </Link>
    </div>
  );
}
