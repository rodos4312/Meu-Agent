# Evaluate the real source selectors with a recording fetcher so the check
# exercises URL and checksum selection without building the full flake.
let
  lock = (builtins.fromJSON (builtins.readFile ../pm/lock.json)).packages;
  lib = {
    inherit (builtins) any mapAttrs;
    filterAttrs = predicate: attrs:
      builtins.listToAttrs (
        map (name: { inherit name; value = attrs.${name}; }) (
          builtins.filter (name: predicate name attrs.${name}) (builtins.attrNames attrs)
        )
      );
    hasSuffix = suffix: value:
      let
        length = builtins.stringLength suffix;
        offset = builtins.stringLength value - length;
      in
      offset >= 0 && builtins.substring offset length value == suffix;
  };

  checkTools = os: arch:
    let
      stdenv = {
        hostPlatform = {
          isAarch64 = arch == "arm64";
          isDarwin = os == "darwin";
          isLinux = os == "linux";
        };
        mkDerivation = attrs: attrs;
      };
      tools = import ./pm-packages.nix {
        inherit lib stdenv;
        fetchurl = attrs: attrs;
        unzip = null;
        autoPatchelfHook = null;
        patchelf = null;
        fetchpatch = null;
      };
      expected = lock.node.artifacts."${os}-${arch}";
    in
    tools.node.srcs == [ { inherit (expected) url sha256; } ];

  npm = import ./npm-pinned.nix {
    stdenv.mkDerivation = attrs: attrs;
    fetchurl = attrs: attrs;
    makeWrapper = null;
    nodejs = null;
  };
in
assert checkTools "linux" "x64";
assert checkTools "linux" "arm64";
assert checkTools "darwin" "arm64";
assert npm.src == { inherit (lock.npm.artifacts.any) url sha256; };
true
