import './App.css';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { HelmetProvider, Helmet } from 'react-helmet-async';
import { CityProvider } from './context/CityContext';
import { Toaster } from './components/ui/toaster';

import Layout from './components/Layout';
import ScrollToTop from './components/ScrollToTop';
import Home from './pages/Home';
import Search from './pages/Search';
import MedDetail from './pages/MedDetail';
import Catalog from './pages/Catalog';
import Categories from './pages/Categories';
import CategoryDetail from './pages/CategoryDetail';
import PharmacyDetail from './pages/PharmacyDetail';
import PharmaciesList from './pages/PharmaciesList';
import ForPharmacies from './pages/ForPharmacies';
import About from './pages/About';
import Contacts from './pages/Contacts';
import Privacy from './pages/Privacy';
import Consent from './pages/Consent';
import NotFound from './pages/NotFound';
import PartnerUpload from './pages/PartnerUpload';
import PartnerAdmin from './pages/PartnerAdmin';

function App() {
  return (
    <HelmetProvider>
      <CityProvider>
        <div className="App">
          <Helmet>
            <html lang="ru" />
            <meta charSet="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <meta name="theme-color" content="#0E9F6E" />
          </Helmet>
          <BrowserRouter>
            <ScrollToTop />
            <Routes>
              <Route path="/" element={<Layout />}>
                {/* default city redirect */}
                <Route index element={<Home />} />

                {/* City-prefixed routes (SEO friendly: /msk/..., /spb/...) */}
                <Route path=":city" element={<Home />} />
                <Route path=":city/poisk" element={<Search />} />
                <Route path=":city/preparaty" element={<Catalog />} />
                <Route path=":city/preparaty/:slug" element={<MedDetail />} />
                <Route path=":city/kategorii" element={<Categories />} />
                <Route path=":city/kategorii/:slug" element={<CategoryDetail />} />
                <Route path=":city/apteki" element={<PharmaciesList />} />
                <Route path=":city/apteki/:id" element={<PharmacyDetail />} />

                {/* Backward-compat (no city prefix) — keep working */}
                <Route path="poisk" element={<Search />} />
                <Route path="preparaty" element={<Catalog />} />
                <Route path="preparaty/:slug" element={<MedDetail />} />
                <Route path="kategorii" element={<Categories />} />
                <Route path="kategorii/:slug" element={<CategoryDetail />} />
                <Route path="apteki" element={<PharmaciesList />} />
                <Route path="apteki/:id" element={<PharmacyDetail />} />

                {/* Static pages — same for all cities */}
                <Route path="dlya-aptek" element={<ForPharmacies />} />
                <Route path="o-servise" element={<About />} />
                <Route path="kontakty" element={<Contacts />} />
                <Route path="politika-konfidencialnosti" element={<Privacy />} />
                <Route path="soglasie-na-obrabotku-pd" element={<Consent />} />
                {/* Hidden partner upload page — NOT linked from main site */}
                <Route path="partner-upload" element={<PartnerUpload />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </BrowserRouter>
          <Toaster />
        </div>
      </CityProvider>
    </HelmetProvider>
  );
}

export default App;
