"""
MRI Appointment Swap System — P2P Exchange Platform
====================================================
A peer-to-peer system allowing patients to exchange MRI appointments
that better fit each other's scheduling needs.

Course: Software Engineering — Final Project
Author: [Your Name]
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class MRIType(str, Enum):
    """Supported MRI scan types."""
    BRAIN = "Brain"
    SPINE = "Spine"
    KNEE = "Knee"
    ABDOMEN = "Abdomen"
    SHOULDER = "Shoulder"
    PELVIS = "Pelvis"


class SwapStatus(str, Enum):
    """Lifecycle states of a swap request."""
    PENDING = "Pending"       # Waiting for a matching partner
    MATCHED = "Matched"       # A match was found; awaiting HMO approval
    APPROVED = "Approved"     # HMO confirmed the swap in the external system
    REJECTED = "Rejected"     # HMO rejected the swap
    CANCELLED = "Cancelled"   # Patient cancelled before finalisation


# ---------------------------------------------------------------------------
# Core Domain Classes
# ---------------------------------------------------------------------------

@dataclass
class Patient:
    """
    Represents a registered patient in the system.

    Attributes:
        name            : Full name of the patient.
        patient_id      : Unique identifier (auto-generated if not supplied).
        hmo_member_id   : HMO membership number used for external API calls.
        contact_email   : Patient's contact e-mail address.
    """

    name: str
    hmo_member_id: str
    contact_email: str
    patient_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __repr__(self) -> str:
        return f"Patient(name={self.name!r}, id={self.patient_id[:8]})"


@dataclass
class Appointment:
    """
    Represents a single MRI appointment slot.

    Attributes:
        patient         : The patient who owns this appointment.
        mri_type        : Type of MRI scan scheduled.
        appointment_date: The date on which the scan is scheduled.
        clinic_name     : Name / identifier of the imaging clinic.
        appointment_id  : Unique identifier (auto-generated if not supplied).
    """

    patient: Patient
    mri_type: MRIType
    appointment_date: date
    clinic_name: str
    appointment_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __repr__(self) -> str:
        return (
            f"Appointment("
            f"patient={self.patient.name!r}, "
            f"type={self.mri_type.value}, "
            f"date={self.appointment_date})"
        )


@dataclass
class SwapRequest:
    """
    Represents a patient's request to exchange their appointment with
    another patient who holds a preferred date.

    Attributes:
        appointment         : The appointment the patient is willing to give up.
        desired_dates       : Ordered list of dates the patient would like instead.
        request_id          : Unique identifier (auto-generated if not supplied).
        status              : Current lifecycle status of the request.
        matched_with        : The partner SwapRequest once a match is found.
    """

    appointment: Appointment
    desired_dates: list[date]
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: SwapStatus = SwapStatus.PENDING
    matched_with: Optional[SwapRequest] = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def patient(self) -> Patient:
        """Shortcut to the owning patient."""
        return self.appointment.patient

    @property
    def mri_type(self) -> MRIType:
        """Shortcut to the MRI type of this request."""
        return self.appointment.mri_type

    @property
    def offered_date(self) -> date:
        """The date this patient is offering to trade."""
        return self.appointment.appointment_date

    def __repr__(self) -> str:
        return (
            f"SwapRequest("
            f"patient={self.patient.name!r}, "
            f"mri={self.mri_type.value}, "
            f"offers={self.offered_date}, "
            f"wants={[str(d) for d in self.desired_dates]}, "
            f"status={self.status.value})"
        )


# ---------------------------------------------------------------------------
# Mock HMO API
# ---------------------------------------------------------------------------

class MockHMO_API:
    """
    Simulates the external Health Maintenance Organisation (HMO) system.

    In production this class would be replaced by real HTTP calls to the
    HMO's REST endpoints.  During testing, every call succeeds deterministically
    so that we can exercise the business logic without network dependencies.

    Methods:
        verify_appointment_exists   : Checks that an appointment is still valid.
        approve_swap                : Records the swap in the HMO system.
    """

    def __init__(self, always_approve: bool = True) -> None:
        """
        Args:
            always_approve: When False the mock simulates an HMO rejection,
                            useful for testing the rejection code-path.
        """
        self._always_approve = always_approve
        self._call_log: list[dict] = []   # audit trail for assertions in tests

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def verify_appointment_exists(self, appointment: Appointment) -> bool:
        """
        Verify that an appointment is still active in the HMO system.

        Args:
            appointment: The appointment to verify.

        Returns:
            True  — appointment is valid (mock always returns True).
            False — appointment was cancelled or not found.
        """
        self._log("verify_appointment_exists", appointment_id=appointment.appointment_id)
        # In the real implementation we would call an HMO REST endpoint here.
        return True

    def approve_swap(
        self,
        request_a: SwapRequest,
        request_b: SwapRequest,
    ) -> bool:
        """
        Register the approved swap in the HMO system, effectively
        re-assigning each appointment to its new owner.

        Args:
            request_a: First party of the swap.
            request_b: Second party of the swap.

        Returns:
            True if the HMO accepted the swap, False otherwise.
        """
        self._log(
            "approve_swap",
            request_a_id=request_a.request_id,
            request_b_id=request_b.request_id,
            patient_a=request_a.patient.name,
            patient_b=request_b.patient.name,
        )
        return self._always_approve

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, method: str, **kwargs) -> None:
        """Record a call to the audit trail."""
        self._call_log.append({"method": method, **kwargs})

    def get_call_log(self) -> list[dict]:
        """Return a copy of all recorded API calls (useful in tests)."""
        return list(self._call_log)


# ---------------------------------------------------------------------------
# Matching Engine
# ---------------------------------------------------------------------------

class MatchingEngine:
    """
    Finds compatible swap pairs from a list of open SwapRequests and,
    when a match is found, coordinates approval via the HMO API.

    Matching criteria (both must hold):
        1. Both requests target the *same* MRI type.
        2. Patient A's offered date appears in Patient B's desired_dates list.
        3. Patient B's offered date appears in Patient A's desired_dates list.

    Time complexity: O(n²) — acceptable for the expected request volume.
    Could be optimised to O(n) with a hash-map if volumes grow.
    """

    def __init__(self, hmo_api: MockHMO_API) -> None:
        """
        Args:
            hmo_api: The (mock or real) HMO API adapter.
        """
        self._hmo = hmo_api

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def find_and_approve_matches(
        self, requests: list[SwapRequest]
    ) -> list[tuple[SwapRequest, SwapRequest]]:
        """
        Scan *requests* for compatible pairs, call the HMO API for each
        match, and update request statuses in-place.

        Args:
            requests: All open swap requests in the system.

        Returns:
            List of (request_a, request_b) tuples that were successfully matched.
        """
        # Work only on pending requests
        pending = [r for r in requests if r.status == SwapStatus.PENDING]
        matched_pairs: list[tuple[SwapRequest, SwapRequest]] = []
        processed_ids: set[str] = set()   # avoid matching the same request twice

        for i, req_a in enumerate(pending):
            if req_a.request_id in processed_ids:
                continue

            for req_b in pending[i + 1:]:
                if req_b.request_id in processed_ids:
                    continue

                if self._is_compatible(req_a, req_b):
                    approved = self._process_match(req_a, req_b)
                    if approved:
                        matched_pairs.append((req_a, req_b))
                        processed_ids.add(req_a.request_id)
                        processed_ids.add(req_b.request_id)
                        break   # req_a is done; move to the next unmatched request

        return matched_pairs

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_compatible(a: SwapRequest, b: SwapRequest) -> bool:
        """
        Return True when a and b satisfy the matching criteria.
        """
        # Rule 1: same MRI type
        if a.mri_type != b.mri_type:
            return False

        # Rule 2: mutual date match
        a_wants_b = b.offered_date in a.desired_dates
        b_wants_a = a.offered_date in b.desired_dates

        return a_wants_b and b_wants_a

    def _process_match(
        self, req_a: SwapRequest, req_b: SwapRequest
    ) -> bool:
        """
        Validate both appointments with the HMO and request approval.
        Updates statuses on both requests accordingly.

        Returns:
            True if the HMO approved the swap.
        """
        # Step 1 — verify both appointments are still valid
        a_valid = self._hmo.verify_appointment_exists(req_a.appointment)
        b_valid = self._hmo.verify_appointment_exists(req_b.appointment)

        if not (a_valid and b_valid):
            # One of the appointments has lapsed — cannot proceed
            return False

        # Step 2 — request HMO approval
        req_a.status = SwapStatus.MATCHED
        req_b.status = SwapStatus.MATCHED
        req_a.matched_with = req_b
        req_b.matched_with = req_a

        approved = self._hmo.approve_swap(req_a, req_b)

        if approved:
            req_a.status = SwapStatus.APPROVED
            req_b.status = SwapStatus.APPROVED
        else:
            req_a.status = SwapStatus.REJECTED
            req_b.status = SwapStatus.REJECTED

        return approved


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestMRISwapSystem:
    """
    Simple unit-test suite that exercises the core scenarios without
    any external dependencies.

    Run with:  python mri_swap_system.py
    """

    def __init__(self) -> None:
        self._passed = 0
        self._failed = 0

    # ------------------------------------------------------------------
    # Assertion helpers
    # ------------------------------------------------------------------

    def _assert(self, condition: bool, message: str) -> None:
        if condition:
            print(f"  ✅  PASS — {message}")
            self._passed += 1
        else:
            print(f"  ❌  FAIL — {message}")
            self._failed += 1

    def _assert_equal(self, actual, expected, message: str) -> None:
        self._assert(actual == expected, f"{message}  (got {actual!r}, expected {expected!r})")

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    def test_successful_1_to_1_swap(self) -> None:
        """
        Scenario: Two patients each hold a Brain MRI appointment on the
        exact date the other patient wants.  The engine should match them
        and the HMO mock should approve the swap.
        """
        print("\n▶  test_successful_1_to_1_swap")

        date_jan = date(2025, 1, 15)
        date_feb = date(2025, 2, 20)

        # --- Create patients ---
        alice = Patient(
            name="Alice Cohen",
            hmo_member_id="HMO-001",
            contact_email="alice@example.com",
        )
        bob = Patient(
            name="Bob Levi",
            hmo_member_id="HMO-002",
            contact_email="bob@example.com",
        )

        # --- Create appointments ---
        alice_appt = Appointment(
            patient=alice,
            mri_type=MRIType.BRAIN,
            appointment_date=date_jan,
            clinic_name="Ichilov Imaging Center",
        )
        bob_appt = Appointment(
            patient=bob,
            mri_type=MRIType.BRAIN,
            appointment_date=date_feb,
            clinic_name="Hadassah MRI Unit",
        )

        # --- Create swap requests ---
        alice_req = SwapRequest(appointment=alice_appt, desired_dates=[date_feb])
        bob_req   = SwapRequest(appointment=bob_appt,  desired_dates=[date_jan])

        self._assert_equal(alice_req.status, SwapStatus.PENDING, "Alice's request starts as PENDING")
        self._assert_equal(bob_req.status,   SwapStatus.PENDING, "Bob's request starts as PENDING")

        # --- Run matching engine ---
        hmo = MockHMO_API(always_approve=True)
        engine = MatchingEngine(hmo_api=hmo)
        matches = engine.find_and_approve_matches([alice_req, bob_req])

        # --- Assertions ---
        self._assert(len(matches) == 1, "Engine found exactly one match")
        self._assert_equal(alice_req.status, SwapStatus.APPROVED, "Alice's request is APPROVED")
        self._assert_equal(bob_req.status,   SwapStatus.APPROVED, "Bob's request is APPROVED")
        self._assert(alice_req.matched_with is bob_req,  "Alice is matched with Bob")
        self._assert(bob_req.matched_with   is alice_req,"Bob is matched with Alice")

        # --- Verify mock was called correctly ---
        log = hmo.get_call_log()
        verify_calls  = [c for c in log if c["method"] == "verify_appointment_exists"]
        approve_calls = [c for c in log if c["method"] == "approve_swap"]
        self._assert(len(verify_calls) == 2,  "HMO.verify_appointment_exists called twice (once per patient)")
        self._assert(len(approve_calls) == 1, "HMO.approve_swap called exactly once")

    def test_no_match_different_mri_type(self) -> None:
        """
        Scenario: Two patients want to swap but have different MRI types.
        The engine must NOT match them.
        """
        print("\n▶  test_no_match_different_mri_type")

        date_a = date(2025, 3, 10)
        date_b = date(2025, 4, 5)

        carol = Patient(name="Carol Mizrahi", hmo_member_id="HMO-003", contact_email="carol@example.com")
        dan   = Patient(name="Dan Shapiro",   hmo_member_id="HMO-004", contact_email="dan@example.com")

        carol_appt = Appointment(patient=carol, mri_type=MRIType.KNEE,  appointment_date=date_a, clinic_name="Clinic A")
        dan_appt   = Appointment(patient=dan,   mri_type=MRIType.SPINE, appointment_date=date_b, clinic_name="Clinic B")

        carol_req = SwapRequest(appointment=carol_appt, desired_dates=[date_b])
        dan_req   = SwapRequest(appointment=dan_appt,   desired_dates=[date_a])

        hmo = MockHMO_API()
        engine = MatchingEngine(hmo_api=hmo)
        matches = engine.find_and_approve_matches([carol_req, dan_req])

        self._assert(len(matches) == 0, "No matches found (different MRI types)")
        self._assert_equal(carol_req.status, SwapStatus.PENDING, "Carol's request remains PENDING")
        self._assert_equal(dan_req.status,   SwapStatus.PENDING, "Dan's request remains PENDING")

    def test_no_match_non_reciprocal_dates(self) -> None:
        """
        Scenario: Both patients share the same MRI type, but their
        desired dates don't align — only one side wants the other's date.
        """
        print("\n▶  test_no_match_non_reciprocal_dates")

        date_a = date(2025, 5, 1)
        date_b = date(2025, 6, 15)
        date_c = date(2025, 7, 20)  # Eve wants this, not date_a

        eve  = Patient(name="Eve Peretz",  hmo_member_id="HMO-005", contact_email="eve@example.com")
        fred = Patient(name="Fred Katz",   hmo_member_id="HMO-006", contact_email="fred@example.com")

        eve_appt  = Appointment(patient=eve,  mri_type=MRIType.ABDOMEN, appointment_date=date_a, clinic_name="Clinic C")
        fred_appt = Appointment(patient=fred, mri_type=MRIType.ABDOMEN, appointment_date=date_b, clinic_name="Clinic D")

        eve_req  = SwapRequest(appointment=eve_appt,  desired_dates=[date_c])   # Eve doesn't want date_b
        fred_req = SwapRequest(appointment=fred_appt, desired_dates=[date_a])   # Fred wants date_a ✓

        hmo = MockHMO_API()
        engine = MatchingEngine(hmo_api=hmo)
        matches = engine.find_and_approve_matches([eve_req, fred_req])

        self._assert(len(matches) == 0, "No match — dates are not mutually compatible")

    def test_hmo_rejection_updates_status(self) -> None:
        """
        Scenario: A valid match is found but the HMO rejects the swap.
        Both requests should be marked REJECTED.
        """
        print("\n▶  test_hmo_rejection_updates_status")

        date_x = date(2025, 8, 10)
        date_y = date(2025, 9, 22)

        gal  = Patient(name="Gal Ben-David", hmo_member_id="HMO-007", contact_email="gal@example.com")
        hila = Patient(name="Hila Nir",      hmo_member_id="HMO-008", contact_email="hila@example.com")

        gal_appt  = Appointment(patient=gal,  mri_type=MRIType.SHOULDER, appointment_date=date_x, clinic_name="Clinic E")
        hila_appt = Appointment(patient=hila, mri_type=MRIType.SHOULDER, appointment_date=date_y, clinic_name="Clinic F")

        gal_req  = SwapRequest(appointment=gal_appt,  desired_dates=[date_y])
        hila_req = SwapRequest(appointment=hila_appt, desired_dates=[date_x])

        # Use a mock that always rejects
        hmo = MockHMO_API(always_approve=False)
        engine = MatchingEngine(hmo_api=hmo)
        matches = engine.find_and_approve_matches([gal_req, hila_req])

        self._assert(len(matches) == 0,                          "No approved matches (HMO rejected)")
        self._assert_equal(gal_req.status,  SwapStatus.REJECTED, "Gal's request is REJECTED")
        self._assert_equal(hila_req.status, SwapStatus.REJECTED, "Hila's request is REJECTED")

    def test_multiple_requests_correct_pairing(self) -> None:
        """
        Scenario: Four patients submit requests.  Only one pair is
        compatible; the engine must pair them and leave the others PENDING.
        """
        print("\n▶  test_multiple_requests_correct_pairing")

        d1 = date(2025, 10, 1)
        d2 = date(2025, 11, 5)
        d3 = date(2025, 12, 20)

        p1 = Patient(name="Ilan Goldberg",  hmo_member_id="HMO-101", contact_email="ilan@example.com")
        p2 = Patient(name="Yael Stern",     hmo_member_id="HMO-102", contact_email="yael@example.com")
        p3 = Patient(name="Ran Avraham",    hmo_member_id="HMO-103", contact_email="ran@example.com")
        p4 = Patient(name="Tali Rosenfeld", hmo_member_id="HMO-104", contact_email="tali@example.com")

        # p1 ↔ p2 can swap (both Brain, mutual dates)
        appt1 = Appointment(patient=p1, mri_type=MRIType.BRAIN, appointment_date=d1, clinic_name="C1")
        appt2 = Appointment(patient=p2, mri_type=MRIType.BRAIN, appointment_date=d2, clinic_name="C2")
        req1 = SwapRequest(appointment=appt1, desired_dates=[d2])
        req2 = SwapRequest(appointment=appt2, desired_dates=[d1])

        # p3 and p4 cannot swap (different types)
        appt3 = Appointment(patient=p3, mri_type=MRIType.PELVIS, appointment_date=d2, clinic_name="C3")
        appt4 = Appointment(patient=p4, mri_type=MRIType.SPINE,  appointment_date=d3, clinic_name="C4")
        req3 = SwapRequest(appointment=appt3, desired_dates=[d3])
        req4 = SwapRequest(appointment=appt4, desired_dates=[d2])

        hmo = MockHMO_API()
        engine = MatchingEngine(hmo_api=hmo)
        matches = engine.find_and_approve_matches([req1, req2, req3, req4])

        self._assert(len(matches) == 1,                        "Exactly one pair matched")
        self._assert_equal(req1.status, SwapStatus.APPROVED,  "p1's request APPROVED")
        self._assert_equal(req2.status, SwapStatus.APPROVED,  "p2's request APPROVED")
        self._assert_equal(req3.status, SwapStatus.PENDING,   "p3's request still PENDING")
        self._assert_equal(req4.status, SwapStatus.PENDING,   "p4's request still PENDING")

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def run_all(self) -> None:
        print("=" * 60)
        print("   MRI SWAP SYSTEM — UNIT TEST SUITE")
        print("=" * 60)

        self.test_successful_1_to_1_swap()
        self.test_no_match_different_mri_type()
        self.test_no_match_non_reciprocal_dates()
        self.test_hmo_rejection_updates_status()
        self.test_multiple_requests_correct_pairing()

        total = self._passed + self._failed
        print("\n" + "=" * 60)
        print(f"   Results: {self._passed}/{total} tests passed")
        if self._failed:
            print(f"   ⚠️  {self._failed} test(s) FAILED — review output above.")
        else:
            print("   🎉  All tests passed!")
        print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    suite = TestMRISwapSystem()
    suite.run_all()
