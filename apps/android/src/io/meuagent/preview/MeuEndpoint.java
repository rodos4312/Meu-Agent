package io.meuagent.preview;

import java.net.URI;
import java.net.URISyntaxException;

final class MeuEndpoint {
    static URI parse(String address) {
        try {
            URI uri = new URI(address.trim());
            int port = uri.getPort();
            String path = uri.getRawPath();
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                    || uri.getRawUserInfo() != null || uri.getRawQuery() != null
                    || uri.getRawFragment() != null || port == 0 || port > 65535
                    || uri.getRawAuthority().endsWith(":")
                    || (!path.isEmpty() && !"/".equals(path))) {
                throw new IllegalArgumentException("Expected an HTTPS origin");
            }
            return new URI("https", null, uri.getHost(), port, "/", null, null);
        } catch (URISyntaxException error) {
            throw new IllegalArgumentException("Expected an HTTPS origin");
        }
    }
}
