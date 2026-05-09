import React from 'react';
import { Helmet } from 'react-helmet-async';

/**
 * Single-purpose SEO component used by every page. Pass an SEO object
 * produced by helpers in `src/seo.js`.
 */
export default function SEOHead({ seo }) {
  if (!seo) return null;
  const { title, description, canonical, image, jsonLd } = seo;
  return (
    <Helmet>
      {title && <title>{title}</title>}
      {description && <meta name="description" content={description} />}
      {canonical && <link rel="canonical" href={canonical} />}
      {title && <meta property="og:title" content={title} />}
      {description && <meta property="og:description" content={description} />}
      <meta property="og:type" content="website" />
      <meta property="og:locale" content="ru_RU" />
      <meta property="og:site_name" content="АптекаА" />
      {canonical && <meta property="og:url" content={canonical} />}
      {image && <meta property="og:image" content={image} />}
      {jsonLd && (
        <script type="application/ld+json">{JSON.stringify(jsonLd)}</script>
      )}
    </Helmet>
  );
}
