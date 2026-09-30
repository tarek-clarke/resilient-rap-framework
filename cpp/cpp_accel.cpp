#include <algorithm>
#include <string>
#include <vector>
#include <pybind11/pybind11.h>

namespace py = pybind11;

int levenshtein_scalar(const std::string& s1, const std::string& s2) {
    const int len1 = static_cast<int>(s1.size());
    const int len2 = static_cast<int>(s2.size());
    std::vector<int> current(len2 + 1), previous(len2 + 1);
    for (int j = 0; j <= len2; ++j) previous[j] = j;

    for (int i = 0; i < len1; ++i) {
        current[0] = i + 1;
        for (int j = 0; j < len2; ++j) {
            current[j + 1] = std::min({
                previous[j + 1] + 1,
                current[j] + 1,
                previous[j] + (s1[i] == s2[j] ? 0 : 1)
            });
        }
        current.swap(previous);
    }
    return previous[len2];
}

int levenshtein_myers(const std::string& s1, const std::string& s2) {
    const int pattern_length = static_cast<int>(s1.size());
    const int text_length = static_cast<int>(s2.size());
    if (pattern_length == 0) return text_length;
    if (text_length == 0) return pattern_length;
    if (pattern_length > 64) return levenshtein_scalar(s1, s2);

    unsigned long long peq[256] = {};
    for (int i = 0; i < pattern_length; ++i) {
        peq[static_cast<unsigned char>(s1[i])] |= (1ULL << i);
    }

    unsigned long long pv = ~0ULL;
    unsigned long long mv = 0ULL;
    int distance = pattern_length;
    for (int i = 0; i < text_length; ++i) {
        const unsigned long long eq = peq[static_cast<unsigned char>(s2[i])];
        const unsigned long long xv = eq | mv;
        const unsigned long long jh = (((eq & pv) + pv) ^ pv) | eq;
        const unsigned long long ph = pv & jh;
        const unsigned long long mh = mv | ~(pv | jh);
        const unsigned long long ph_shifted = (ph << 1) | 1ULL;
        const unsigned long long mh_shifted = mh << 1;

        pv = mh_shifted | ~(ph_shifted | xv);
        mv = ph_shifted & xv;
        if (ph_shifted & (1ULL << (pattern_length - 1))) ++distance;
        if (mh_shifted & (1ULL << (pattern_length - 1))) --distance;
    }
    return distance;
}

PYBIND11_MODULE(cpp_accel, module) {
    module.doc() = "Optional C++ Levenshtein distance accelerator";
    module.def(
        "levenshtein_cpp",
        &levenshtein_myers,
        "Compute Levenshtein distance with Myers' bit-parallel algorithm",
        py::arg("s1"),
        py::arg("s2")
    );
}
