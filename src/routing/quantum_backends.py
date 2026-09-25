"""
quantum_backends.py – Abstract backend interface for quantum circuit execution.

Provides pluggable backends for the quantum routing module:
  - QiskitAerBackend  : local Aer simulator (default)
  - IBMQuantumBackend : IBM Quantum hardware via qiskit-ibm-runtime
  - LumiQBackend      : LUMI-Q / VTT Q50 (53-qubit) via FiQCI
  - VLQBackend        : IT4Innovations VLQ (Ostrava, 24-qubit IQM) via LEXIS QaaS

Use the ``get_backend`` factory to instantiate by name.

Credentials note
----------------
The ``VLQBackend`` reads all project/resource identifiers from environment
variables at runtime.  **Never hard-code VLQ project or resource IDs in
this file.**  Set them in a local ``.env`` file (which is git-ignored) or
export them in your shell before invoking any QPU run.
"""

import os
from abc import ABC, abstractmethod
from typing import Dict, Optional


class QuantumBackend(ABC):
    """Abstract quantum backend interface."""

    @abstractmethod
    def execute_circuit(self, circuit, shots: int = 1024) -> Dict:
        """Execute a quantum circuit and return measurement counts."""
        pass

    @abstractmethod
    def get_backend_info(self) -> Dict:
        """Return backend configuration info."""
        pass


class QiskitAerBackend(QuantumBackend):
    """Local Qiskit Aer simulator backend."""

    def __init__(self) -> None:
        self._simulator = None

    def _init(self) -> None:
        try:
            from qiskit_aer import AerSimulator
            self._simulator = AerSimulator()
        except ImportError:
            raise ImportError(
                "qiskit-aer not installed. Run: pip install -r requirements-quantum.txt"
            )

    def execute_circuit(self, circuit, shots: int = 1024) -> Dict:
        if self._simulator is None:
            self._init()
        from qiskit import transpile
        transpiled = transpile(circuit, self._simulator)
        job = self._simulator.run(transpiled, shots=shots)
        return job.result().get_counts()

    def get_backend_info(self) -> Dict:
        return {"type": "simulator", "name": "aer_simulator", "provider": "qiskit"}


class IBMQuantumBackend(QuantumBackend):
    """IBM Quantum/Cloud hardware backend."""

    def __init__(self, instance: str = "ibm-q/open/main", min_qubits: int = 12) -> None:
        self.instance = instance
        self.min_qubits = min_qubits
        self._backend = None

    def _init(self) -> None:
        try:
            from qiskit_ibm_runtime import QiskitRuntimeService
            service = None

            # 1. Try loading as ibm_cloud first if the instance is a CRN
            if self.instance and self.instance.startswith("crn:"):
                try:
                    service = QiskitRuntimeService(channel="ibm_cloud", instance=self.instance)
                except Exception as e:
                    print(f"[IBMQuantumBackend] Failed to load via ibm_cloud with instance CRN: {e}")

            # 2. Try loading default saved accounts (from environment/file)
            if service is None:
                try:
                    service = QiskitRuntimeService()
                except Exception:
                    pass

            # 3. Try loading ibm_cloud channel generally
            if service is None:
                try:
                    service = QiskitRuntimeService(channel="ibm_cloud")
                except Exception:
                    pass

            # 4. Try loading ibm_quantum / ibm_quantum_platform channel generally
            if service is None:
                token = os.environ.get("QISKIT_IBM_TOKEN")
                for ch in ["ibm_quantum_platform", "ibm_quantum"]:
                    try:
                        if token:
                            service = QiskitRuntimeService(channel=ch, token=token)
                        else:
                            service = QiskitRuntimeService(channel=ch)
                        if service:
                            break
                    except Exception:
                        pass

            if service is None:
                raise ValueError("Could not initialize QiskitRuntimeService on any channel. Please check your credentials.")

            self._backend = service.least_busy(min_num_qubits=self.min_qubits)
        except ImportError:
            raise ImportError("qiskit-ibm-runtime not installed.")

    def execute_circuit(self, circuit, shots: int = 1024) -> Dict:
        if self._backend is None:
            self._init()
        from qiskit import transpile
        transpiled = transpile(circuit, self._backend)
        job = self._backend.run(transpiled, shots=shots)
        return job.result().get_counts()

    def get_backend_info(self) -> Dict:
        name = self._backend.name if self._backend else "not_initialized"
        return {
            "type": "hardware",
            "name": name,
            "provider": "ibm_quantum",
            "instance": self.instance,
        }


class LumiQBackend(QuantumBackend):
    """LUMI-Q hardware backend (VTT 24-qubit or VTT Q50) via FiQCI."""

    def __init__(self, endpoint: Optional[str] = None) -> None:
        import os
        # Fall back to env var HELMI_CORTEX_URL if no endpoint is passed explicitly
        self.endpoint = endpoint or os.getenv("HELMI_CORTEX_URL")
        self._backend = None

    def _init(self) -> None:
        if not self.endpoint:
            raise ValueError(
                "LUMI-Q Cortex URL is not configured. Please export HELMI_CORTEX_URL or pass --endpoint."
            )
        try:
            # Support both package layouts of qiskit-iqm
            try:
                from iqm.qiskit_iqm import IQMProvider
            except ImportError:
                from qiskit_iqm import IQMProvider

            provider = IQMProvider(self.endpoint)
            self._backend = provider.get_backend()
        except ImportError:
            raise ImportError(
                "qiskit-iqm is not installed. Please run: pip install qiskit-iqm"
            )

    def execute_circuit(self, circuit, shots: int = 1024) -> Dict:
        if self._backend is None:
            try:
                self._init()
            except Exception as e:
                print(f"[LumiQBackend] Failed to connect to physical QPU ({e}). Falling back to AerSimulator.")
                from qiskit_aer import AerSimulator
                sim = AerSimulator()
                from qiskit import transpile
                transpiled = transpile(circuit, sim)
                job = sim.run(transpiled, shots=shots)
                return job.result().get_counts()

        from qiskit import transpile
        transpiled = transpile(circuit, self._backend)
        job = self._backend.run(transpiled, shots=shots)
        return job.result().get_counts()

    def get_backend_info(self) -> Dict:
        name = self._backend.name if self._backend else "lumi_q"
        return {
            "type": "quantum_hpc",
            "name": name,
            "provider": "FiQCI/VTT",
            "qubits": 24,
            "endpoint": self.endpoint,
        }


class VLQBackend(QuantumBackend):
    """IT4Innovations VLQ (Ostrava) backend via LEXIS QaaS.

    The VLQ is a 24-qubit IQM superconducting QPU hosted at the
    IT4Innovations National Supercomputing Center under EuroHPC JU.
    It is accessed through the LEXIS platform using the ``py4lexis``
    and ``qaas`` Python packages.

    Credentials are read **exclusively from environment variables**::

        VLQ_PROJECT  – EuroHPC project ID  (e.g. OPEN-37-1)
        VLQ_RESOURCE – Queue/resource name  (e.g. VLQ-CZ)

    Never hard-code these values in source files committed to version
    control.  Store them in a local ``.env`` file (git-ignored) or
    export them in your shell session.

    Parameters
    ----------
    project : str, optional
        Overrides ``VLQ_PROJECT`` env var.  Use only in trusted,
        non-version-controlled scripts.
    resource : str, optional
        Overrides ``VLQ_RESOURCE`` env var.
    batch_size : int
        Maximum circuits to bundle into a single QaaS job submission.
        Larger batches reduce per-call overhead dramatically (default 100).
    """

    #: VLQ system specification (24-qubit IQM, star topology, 2600 CLOPS)
    SYSTEM_INFO: Dict = {
        "name": "VLQ",
        "provider": "IQM / IT4Innovations",
        "location": "Ostrava, CZ",
        "qubits": 24,
        "topology": "star",
        "clops": 2600,
        "single_qubit_gate_ns": 40,
        "two_qubit_gate_ns": 60,
        "access": "EuroHPC JU / LEXIS QaaS",
    }

    def __init__(
        self,
        project: Optional[str] = None,
        resource: Optional[str] = None,
        batch_size: int = 100,
    ) -> None:
        import os
        self._project: str = project or os.environ.get("VLQ_PROJECT", "")
        self._resource: str = resource or os.environ.get("VLQ_RESOURCE", "")
        self.batch_size: int = batch_size
        self._backend = None   # qaas.QBackend, populated lazily
        self._token: Optional[str] = None

        if not self._project:
            raise ValueError(
                "VLQ project ID not configured. "
                "Export VLQ_PROJECT=<your-project-id> before running."
            )
        if not self._resource:
            raise ValueError(
                "VLQ resource not configured. "
                "Export VLQ_RESOURCE=<resource-id> (e.g. VLQ-CZ) before running."
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _authenticate(self) -> str:
        """Trigger LEXIS OAuth2 flow and return a fresh access token."""
        # Check for local gitignored token override
        token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "lexis_token.txt")
        if os.path.exists(token_path):
            print(f"[VLQBackend] Found cached token at {token_path}, loading...")
            try:
                with open(token_path, "r") as tf:
                    token = tf.read().strip()
                if token:
                    return token
            except Exception as e:
                print(f"[VLQBackend] Warning: Failed to read token file: {e}")

        try:
            from py4lexis.session import LexisSession  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "py4lexis is not installed. "
                "Run: pip install --index-url "
                "https://opencode.it4i.eu/api/v4/projects/107/packages/pypi/simple py4lexis"
            ) from exc

        print("[VLQBackend] Opening LEXIS authentication page …")
        session = LexisSession()
        token = session.get_access_token()
        if not token:
            raise RuntimeError("LEXIS authentication failed: no token returned.")
        print("[VLQBackend] Token obtained successfully.")
        return token

    def _init(self) -> None:
        """Authenticate and bind to the VLQ QaaS backend."""
        try:
            from qaas.client import QProvider  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "qaas is not installed. Run: pip install qaas==v0.3.2"
            ) from exc

        self._token = self._authenticate()
        # QaaS 0.4.x takes the project as the first argument and the OAuth
        # token by keyword.  The legacy positional order makes the JWT look
        # like a project identifier and fails before any VLQ job is created.
        provider = QProvider(self._project, token=self._token)
        self._backend = provider.get_backend(self._resource)
        print(
            f"[VLQBackend] Connected to resource '{self._resource}' "
            f"on project '{self._project}'."
        )

    # ------------------------------------------------------------------
    # QuantumBackend interface
    # ------------------------------------------------------------------

    def execute_circuit(self, circuit, shots: int = 1024) -> Dict:
        """Execute a single Qiskit circuit on the VLQ QPU.

        The circuit is transpiled with Qiskit's standard transpiler then
        submitted to the VLQ via QaaS.  Results are returned as a standard
        Qiskit counts dict (bitstring -> count).
        """
        if self._backend is None:
            self._init()
        from qiskit import transpile
        transpiled = transpile(circuit, self._backend)
        job = self._backend.run(transpiled, shots=shots)
        return job.result().get_counts()

    def execute_batch(self, circuits: list, shots: int = 1024) -> list:
        """Submit a list of circuits in batches to minimise QaaS overhead.

        Circuits are dynamically packed (multi-programming) into the QPU's width
        to maximize throughput (e.g. packing two 12-qubit circuits into 24 qubits).
        
        Returns
        -------
        list[dict]
            One counts dict per input circuit, in original order.
        """
        if self._backend is None:
            self._init()

        from qiskit import transpile, QuantumCircuit

        qubits_per_circuit = circuits[0].num_qubits
        clbits_per_circuit = circuits[0].num_clbits
        pack_size = 24 // qubits_per_circuit if qubits_per_circuit > 0 else 1
        pack_size = max(1, pack_size)
        
        packed_circuits = []
        pack_lengths = []
        
        for i in range(0, len(circuits), pack_size):
            chunk = circuits[i : i + pack_size]
            pack_lengths.append(len(chunk))
            if len(chunk) == 1:
                packed_circuits.append(chunk[0])
            else:
                packed_qc = QuantumCircuit(len(chunk) * qubits_per_circuit, len(chunk) * clbits_per_circuit)
                for j, qc in enumerate(chunk):
                    q_offset = j * qubits_per_circuit
                    c_offset = j * clbits_per_circuit
                    packed_qc.compose(
                        qc,
                        qubits=list(range(q_offset, q_offset + qubits_per_circuit)),
                        clbits=list(range(c_offset, c_offset + clbits_per_circuit)),
                        inplace=True
                    )
                packed_circuits.append(packed_qc)

        all_counts: list = []
        total = len(packed_circuits)
        
        for start in range(0, total, self.batch_size):
            chunk = packed_circuits[start : start + self.batch_size]
            chunk_lengths = pack_lengths[start : start + self.batch_size]
            
            transpiled_chunk = [transpile(c, self._backend) for c in chunk]
            n_batch = start // self.batch_size + 1
            n_total = (total - 1) // self.batch_size + 1
            print(
                f"[VLQBackend] Submitting batch {n_batch}/{n_total} "
                f"({len(chunk)} packed circuits, containing {sum(chunk_lengths)} original circuits) …"
            )
            job = self._backend.run(transpiled_chunk, shots=shots)
            result = job.result()
            for i, p_len in enumerate(chunk_lengths):
                try:
                    packed_counts = result.get_counts(i)
                except Exception:
                    packed_counts = result.get_counts()
                    
                if p_len == 1:
                    all_counts.append(packed_counts)
                else:
                    unpacked_dicts = [{} for _ in range(p_len)]
                    for bitstring, count in packed_counts.items():
                        clean_bits = bitstring.replace(" ", "")
                        for j in range(p_len):
                            end_idx = len(clean_bits) - j * clbits_per_circuit
                            start_idx = len(clean_bits) - (j + 1) * clbits_per_circuit
                            c_bits = clean_bits[start_idx:end_idx]
                            unpacked_dicts[j][c_bits] = unpacked_dicts[j].get(c_bits, 0) + count
                            
                    all_counts.extend(unpacked_dicts)

        return all_counts

    def get_backend_info(self) -> Dict:
        return {
            **self.SYSTEM_INFO,
            "type": "quantum_hpc",
            "batch_size": self.batch_size,
            "project": self._project,
            "resource": self._resource,
        }


def get_backend(name: str, **kwargs) -> QuantumBackend:
    """Factory function to get a quantum backend by name.

    Parameters
    ----------
    name : str
        One of ``"aer_simulator"``, ``"ibm_quantum"``, ``"lumi_q"``,
        or ``"vlq"``.
    **kwargs
        Forwarded to the backend constructor.

    Returns
    -------
    QuantumBackend
        An initialised backend instance.

    Notes
    -----
    The ``"vlq"`` backend requires ``VLQ_PROJECT`` and ``VLQ_RESOURCE``
    to be set as environment variables before calling this function.
    """
    backends = {
        "aer_simulator": QiskitAerBackend,
        "ibm_quantum": IBMQuantumBackend,
        "lumi_q": LumiQBackend,
        "vlq": VLQBackend,
    }
    if name not in backends:
        print(f"[WARNING] Unknown backend '{name}', falling back to aer_simulator")
        return QiskitAerBackend()
    return backends[name](**kwargs)
