#!/usr/bin/env bash
# Download public headers for ABI verification into tests/headers/<project>/<version>/.

set -euo pipefail

ROOT=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )
FORCE=0
if [[ ${1:-} == --force ]]; then
    FORCE=1
    shift
fi
TARGET=${1:-all}
shift || true

prepare_repository() {
    local project=$1
    local url=$2
    local cache="$ROOT/$project/.repo"
    if [[ -d "$cache/.git" ]]; then
        if ! git -C "$cache" fetch --quiet --tags --prune --force origin; then
            rm -rf "$cache"
        fi
    fi
    if [[ ! -d "$cache/.git" ]]; then
        rm -rf "$cache"
        mkdir -p "$ROOT/$project"
        if ! git clone --quiet --filter=blob:none --no-checkout "$url" "$cache"; then
            rm -rf "$cache"
            git clone --quiet --no-checkout "$url" "$cache"
        fi
    fi
    echo "$cache"
}

create_worktree() {
    local cache=$1
    local ref=$2
    local worktree
    worktree=$( mktemp -d "$( dirname -- "$cache" )/.worktree.XXXXXX" )
    rmdir "$worktree"
    git -C "$cache" worktree add --quiet --detach --force "$worktree" "$ref"
    echo "$worktree"
}

remove_worktree() {
    local cache=$1
    local worktree=$2
    git -C "$cache" worktree remove --force "$worktree" >/dev/null 2>&1 || rm -rf "$worktree"
    git -C "$cache" worktree prune
}

libfuse_tag() {
    local cache=$1
    local version=$2
    local tag="fuse-$version"
    if ! git -C "$cache" rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
        tag="fuse_${version//./_}"
    fi
    if ! git -C "$cache" rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
        echo "Unknown libfuse tag for version $version" >&2
        return 1
    fi
    echo "$tag"
}

fetch_libfuse() {
    local versions=("$@")
    if [[ ${#versions[@]} -eq 0 ]]; then
        versions=(
            2.7.0
            2.8.0 2.8.1 2.8.2 2.8.3 2.8.4 2.8.5 2.8.6 2.8.7
            2.9.0 2.9.1 2.9.2 2.9.3 2.9.4 2.9.5 2.9.6 2.9.7 2.9.8 2.9.9
            3.0.0 3.0.1 3.0.2
            3.1.0 3.1.1
            3.2.0 3.2.1 3.2.2 3.2.3 3.2.4 3.2.5 3.2.6
            3.3.0
            3.4.1 3.4.2
            3.5.0
            3.6.0 3.6.1 3.6.2
            3.7.0
            3.8.0
            3.9.0 3.9.1 3.9.2 3.9.3 3.9.4
            3.10.0 3.10.1 3.10.2 3.10.3 3.10.4 3.10.5
            3.11.0
            3.12.0
            3.13.0 3.13.1
            3.14.0 3.14.1
            3.15.0 3.15.1
            3.16.1 3.16.2
            3.17.1 3.17.2 3.17.3 3.17.4
            3.18.0 3.18.1 3.18.2 3.18.3
            master
        )
    fi

    local cache
    cache=$( prepare_repository libfuse https://github.com/libfuse/libfuse.git )
    local version
    for version in "${versions[@]}"; do
        local destination="$ROOT/libfuse/$version"
        local include_dir=fuse3
        [[ $version == 2.* ]] && include_dir=fuse
        if [[ -f "$destination/include/$include_dir/fuse.h" && $FORCE -eq 0 ]]; then
            echo "Skipping libfuse $version, already present"
            continue
        fi

        local ref
        if [[ $version == master ]]; then
            ref=origin/master
        else
            ref=$( libfuse_tag "$cache" "$version" )
        fi
        local worktree
        worktree=$( create_worktree "$cache" "$ref" )
        rm -rf "$destination"
        mkdir -p "$destination/include/$include_dir"
        cp "$worktree"/include/*.h "$destination/include/$include_dir/"

        local major minor hotfix
        if [[ $version == master ]]; then
            # The unreleased development version is modeled as the next minor release.
            major=3
            minor=19
            hotfix=0
        else
            IFS=. read -r major minor hotfix <<< "$version"
        fi
        if [[ $major -ge 3 ]]; then
            cat > "$destination/include/$include_dir/libfuse_config.h" <<EOF
#pragma once
#define FUSE_MAJOR_VERSION $major
#define FUSE_MINOR_VERSION $minor
#define FUSE_HOTFIX_VERSION ${hotfix:-0}
#define FUSE_RC_VERSION ""
EOF
            cp "$destination/include/$include_dir/libfuse_config.h" \
                "$destination/include/$include_dir/fuse_config.h"
        fi

        local license
        license=$( find "$worktree" -maxdepth 2 \( -iname 'LGPL*' -o -iname 'COPYING*' \) -type f -print -quit )
        if [[ -n "$license" ]]; then
            cp "$license" "$destination/"
        fi
        remove_worktree "$cache" "$worktree"
        echo "libfuse $version -> $destination"
    done
}

fetch_winfsp() {
    local versions=("$@")
    if [[ ${#versions[@]} -eq 0 ]]; then
        versions=(1.11 1.12 2.0 2.1 2.2)
    fi

    local cache
    cache=$( prepare_repository winfsp https://github.com/winfsp/winfsp.git )
    local version
    for version in "${versions[@]}"; do
        local destination="$ROOT/winfsp/$version"
        if [[ -f "$destination/include/fuse/fuse.h" && $FORCE -eq 0 ]]; then
            echo "Skipping WinFsp $version, already present"
            continue
        fi

        local worktree
        worktree=$( create_worktree "$cache" "v$version" )
        rm -rf "$destination"
        mkdir -p "$destination/include"
        cp -r "$worktree/inc/fuse" "$destination/include/"
        [[ -d "$worktree/inc/fuse3" ]] && cp -r "$worktree/inc/fuse3" "$destination/include/"

        local license
        license=$( find "$worktree" -maxdepth 2 -iname 'LICENSE*' -type f -print -quit )
        if [[ -n "$license" ]]; then
            cp "$license" "$destination/"
        fi
        remove_worktree "$cache" "$worktree"
        echo "WinFsp $version -> $destination"
    done
}

fetch_macfuse() {
    local branches=("$@")
    if [[ ${#branches[@]} -eq 0 ]]; then
        # macFUSE 5.5.0 pins Library-2 to support/libfuse-2.9. The 3.17 and 3.18
        # branches cover the newer libfuse 3.x layouts.
        branches=(support/libfuse-2.9 support/libfuse-3.17 support/libfuse-3.18)
    fi

    local cache
    cache=$( prepare_repository macfuse https://github.com/macfuse/library.git )
    local branch
    for branch in "${branches[@]}"; do
        local version=${branch//\//-}
        local destination="$ROOT/macfuse/$version"
        if [[ -f "$destination/include/fuse/fuse.h" && $FORCE -eq 0 ]]; then
            echo "Skipping macFUSE $branch, already present"
            continue
        fi

        local worktree
        worktree=$( create_worktree "$cache" "origin/$branch" )
        rm -rf "$destination"
        mkdir -p "$destination/include/fuse"
        cp "$worktree"/include/*.h "$destination/include/fuse/"

        local major minor hotfix
        case "$branch" in
            support/libfuse-3.17) major=3; minor=17; hotfix=4 ;;
            support/libfuse-3.18) major=3; minor=18; hotfix=3 ;;
            *) major=2; minor=9; hotfix=0 ;;
        esac
        if [[ $major -ge 3 ]]; then
            cat > "$destination/include/fuse/libfuse_config.h" <<EOF
#pragma once
#define FUSE_MAJOR_VERSION $major
#define FUSE_MINOR_VERSION $minor
#define FUSE_HOTFIX_VERSION $hotfix
#define FUSE_RC_VERSION ""
EOF
            cp "$destination/include/fuse/libfuse_config.h" \
                "$destination/include/fuse/fuse_config.h"
        fi

        local license
        license=$( find "$worktree" -maxdepth 2 \( -iname 'LICENSE*' -o -iname 'COPYING*' \) -type f -print -quit )
        if [[ -n "$license" ]]; then
            cp "$license" "$destination/"
        fi
        remove_worktree "$cache" "$worktree"
        echo "macFUSE $branch -> $destination"
    done
}

fetch_netbsd() {
    local version=${1:-netbsd-11}
    local destination="$ROOT/netbsd/$version"
    if [[ -f "$destination/include/fuse/fuse.h" && $FORCE -eq 0 ]]; then
        echo "Skipping NetBSD $version, already present"
        return
    fi

    rm -rf "$destination"
    mkdir -p "$destination/include/fuse" "$destination/include/sys"
    local base="https://raw.githubusercontent.com/NetBSD/src/$version"
    local file
    # NetBSD's librefuse has a monolithic fuse.h and no fuse_common.h.
    for file in fuse.h fuse_lowlevel.h fuse_opt.h fuse_log.h; do
        curl -fsSL "$base/lib/librefuse/$file" -o "$destination/include/fuse/$file"
    done
    for file in stat.h statvfs.h fcntl.h; do
        curl -fsSL "$base/sys/sys/$file" -o "$destination/include/sys/$file"
    done
    mkdir -p "$destination/include/fuse/refuse"
    for file in buf.h chan.h fs.h legacy.h poll.h session.h v11.h v21.h v22.h v23.h v25.h v26.h v28.h v29.h v30.h v32.h v34.h v35.h v38.h; do
        curl -fsSL "$base/lib/librefuse/refuse/$file" -o "$destination/include/fuse/refuse/$file"
    done
    echo "NetBSD $version -> $destination"
}

fetch_openbsd() {
    local version=${1:-master}
    local destination="$ROOT/openbsd/$version"
    if [[ -f "$destination/include/fuse/fuse.h" && $FORCE -eq 0 ]]; then
        echo "Skipping OpenBSD $version, already present"
        return
    fi

    rm -rf "$destination"
    mkdir -p "$destination/include/fuse" "$destination/include/sys"
    local base="https://raw.githubusercontent.com/openbsd/src/$version"
    local file
    for file in fuse.h fuse_common.h fuse_lowlevel.h fuse_opt.h; do
        curl -fsSL "$base/lib/libfuse/$file" -o "$destination/include/fuse/$file"
    done
    for file in stat.h statvfs.h fcntl.h; do
        curl -fsSL "$base/sys/sys/$file" -o "$destination/include/sys/$file"
    done
    echo "OpenBSD $version -> $destination"
}

fetch_freebsd() {
    local version=${1:-releng/14.3}
    local destination="$ROOT/freebsd/${version//\//-}"
    if [[ -f "$destination/include/sys/stat.h" && $FORCE -eq 0 ]]; then
        echo "Skipping FreeBSD $version, already present"
        return
    fi

    rm -rf "$destination"
    mkdir -p "$destination/include/sys"
    local base="https://raw.githubusercontent.com/freebsd/freebsd-src/$version"
    local file
    for file in stat.h statvfs.h fcntl.h; do
        curl -fsSL "$base/sys/sys/$file" -o "$destination/include/sys/$file"
    done
    # FreeBSD's fusefs-libs port builds the upstream libfuse headers, so use the libfuse tree above.
    echo "FreeBSD $version -> $destination"
}

fetch_cygfuse() {
    local versions=("$@")
    if [[ ${#versions[@]} -eq 0 ]]; then
        versions=(3.2.0-2 3.2.0-3)
    fi

    local version
    for version in "${versions[@]}"; do
        local destination="$ROOT/cygfuse/$version"
        if [[ -f "$destination/include/fuse/fuse_common.h" && $FORCE -eq 0 ]]; then
            echo "Skipping cygfuse $version, already present"
            continue
        fi

        rm -rf "$destination"
        mkdir -p "$destination/include/fuse" "$destination/include/fuse3"
        local temporary
        temporary=$(mktemp -d)
        local package="cygfuse-$version-src.tar.xz"
        curl -fsSL "https://mirrors.kernel.org/sourceware/cygwin/x86_64/release/cygfuse/$package" \
            -o "$temporary/$package"
        tar -xJf "$temporary/$package" -C "$temporary"
        mkdir -p "$temporary/source"
        tar -xJf "$temporary/cygfuse-$version.src/cygfuse-$version-src.tar.xz" -C "$temporary/source"
        # Only the headers are needed. The GPLv3 notice is in each copied header.
        cp "$temporary/source/cygfuse/fuse"/*.h "$destination/include/fuse/"
        cp "$temporary/source/cygfuse/fuse3"/*.h "$destination/include/fuse3/"

        local license
        license=$( find "$temporary" -maxdepth 4 \( -iname 'COPYING*' -o -iname 'LICENSE*' \) -type f -print -quit )
        if [[ -n "$license" ]]; then
            cp "$license" "$destination/"
        fi
        rm -rf "$temporary"
        echo "cygfuse $version -> $destination"
    done
}

case "$TARGET" in
    all)
        fetch_libfuse
        fetch_winfsp
        fetch_macfuse
        fetch_netbsd
        fetch_openbsd
        fetch_freebsd
        fetch_cygfuse
        ;;
    libfuse|winfsp|macfuse|netbsd|openbsd|freebsd|cygfuse)
        "fetch_$TARGET" "$@"
        ;;
    *)
        echo "Usage: $0 [--force] [all|libfuse|winfsp|macfuse|netbsd|openbsd|freebsd|cygfuse] [version ...]" >&2
        exit 1
        ;;
esac
