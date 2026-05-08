import './App.css';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { CityProvider } from './context/CityContext';
import { Toaster } from './components/ui/toaster';

import Layout from './components/Layout';
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

function App() {
  return (
    <CityProvider>
      <div className="App">
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Layout />}>
              <Route index element={<Home />} />
              <Route path="poisk" element={<Search />} />
              <Route path="preparaty" element={<Catalog />} />
              <Route path="preparaty/:slug" element={<MedDetail />} />
              <Route path="kategorii" element={<Categories />} />
              <Route path="kategorii/:slug" element={<CategoryDetail />} />
              <Route path="apteki" element={<PharmaciesList />} />
              <Route path="apteki/:id" element={<PharmacyDetail />} />
              <Route path="dlya-aptek" element={<ForPharmacies />} />
              <Route path="o-servise" element={<About />} />
              <Route path="kontakty" element={<Contacts />} />
              <Route path="politika-konfidencialnosti" element={<Privacy />} />
              <Route path="soglasie-na-obrabotku-pd" element={<Consent />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster />
      </div>
    </CityProvider>
  );
}

export default App;
