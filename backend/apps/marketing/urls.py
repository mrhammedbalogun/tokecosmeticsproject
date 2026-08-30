from django.urls import path

from apps.marketing.views import MarketingConfigView, product_feed

urlpatterns = [
    path("config/", MarketingConfigView.as_view(), name="marketing-config"),
    # The product catalogue for the ad platforms' shopping feeds. `.xml` in the path
    # because Meta's and Google's feed fetchers both key on the extension when guessing
    # the format, and a feed served from an extensionless URL is a support thread.
    path("feed/products.xml", product_feed, name="marketing-product-feed"),
]
