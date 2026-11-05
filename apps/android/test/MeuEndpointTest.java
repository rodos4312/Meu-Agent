package io.meuagent.preview;

public final class MeuEndpointTest {
    public static void main(String[] args) {
        if (!MeuEndpoint.parse(" https://meu.example:8443/ ").resolve("v1/runs").toString()
                .equals("https://meu.example:8443/v1/runs")) {
            throw new AssertionError("HTTPS gateway and port must survive parsing");
        }
        if (!MeuEndpoint.parse("https://[::1]").resolve("v1/runs").toString()
                .equals("https://[::1]/v1/runs")) {
            throw new AssertionError("IPv6 gateway must survive parsing");
        }
        for (String invalid : new String[] {"http://meu.example", "https://user@meu.example",
                "https://meu.example:65536", "https://meu.example:", "https://meu.example:0",
                "https://meu.example/other", "https://meu.example/?key=x", "https://meu.example/#x",
                "https:///meu.example", "https:meu.example", "https://meu.example\\@other.example"}) {
            try {
                MeuEndpoint.parse(invalid);
                throw new AssertionError("Accepted invalid gateway: " + invalid);
            } catch (IllegalArgumentException expected) {
                // Invalid addresses cannot receive the gateway credential.
            }
        }
        System.out.println("Meu Android HTTPS endpoint checks passed.");
    }
}
