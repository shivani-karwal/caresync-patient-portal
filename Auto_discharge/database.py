# ============================================================
# FILE: database.py
# PURPOSE: All database read/write functions
# ============================================================

import logging
import mysql.connector
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger("hospital.discharge")


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


# ============================================================
# PATIENT FUNCTIONS
# ============================================================

def get_patient(patient_id):

    conn = get_connection()

    try:

        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM patients
            WHERE id = %s
            """,
            (patient_id,)
        )

        return cursor.fetchone()

    finally:

        conn.close()


def get_all_patients():

    conn = get_connection()

    try:

        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                id,
                name,
                age,
                gender
            FROM patients
            ORDER BY id
            """
        )

        return cursor.fetchall()

    finally:

        conn.close()


# ============================================================
# FIND EMPTY BED
# ============================================================

def find_empty_bed(ward):

    conn = get_connection()

    try:

        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                bed_id,
                bed_number,
                bed_type
            FROM beds
            WHERE ward = %s
              AND is_occupied = 0
            LIMIT 1
            """,
            (ward,)
        )

        return cursor.fetchone()

    finally:

        conn.close()


# ============================================================
# ON DUTY NURSE
# ============================================================

def get_on_duty_nurse(ward):

    conn = get_connection()

    try:

        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                nurse_name,
                shift_start,
                shift_end
            FROM staff_shifts
            WHERE ward = %s
              AND is_on_duty = 1
            LIMIT 1
            """,
            (ward,)
        )

        return cursor.fetchone()

    finally:

        conn.close()


# ============================================================
# ASSIGN BED
# ============================================================

def assign_bed_to_patient(
    patient_id,
    bed_id,
    nurse_name
):

    conn = get_connection()

    cursor = conn.cursor()

    try:

        # Check patient exists

        cursor.execute(
            """
            SELECT id
            FROM patients
            WHERE id = %s
            """,
            (patient_id,)
        )

        patient = cursor.fetchone()

        if not patient:

            raise Exception(
                "Patient not found."
            )


        # Check bed is available

        cursor.execute(
            """
            SELECT
                bed_id,
                is_occupied,
                patient_id
            FROM beds
            WHERE bed_id = %s
            """,
            (bed_id,)
        )

        bed = cursor.fetchone()

        if not bed:

            raise Exception(
                "Bed not found."
            )


        if bed[1] != 0:

            raise Exception(
                "Bed is already occupied."
            )


        # Assign patient to bed

        cursor.execute(
            """
            UPDATE beds
            SET
                is_occupied = 1,
                patient_id = %s
            WHERE bed_id = %s
              AND is_occupied = 0
            """,
            (
                patient_id,
                bed_id
            )
        )


        if cursor.rowcount != 1:

            raise Exception(
                "Bed assignment failed."
            )


        # Save assignment history

        cursor.execute(
            """
            INSERT INTO bed_assignments
            (
                patient_id,
                bed_id,
                nurse_assigned,
                assigned_at,
                assigned_by
            )
            VALUES
            (
                %s,
                %s,
                %s,
                NOW(),
                'ai_agent'
            )
            """,
            (
                patient_id,
                bed_id,
                nurse_name
            )
        )


        conn.commit()

        return True


    except Exception as e:

        conn.rollback()

        logger.exception(
            "Bed assignment failed"
        )

        print(
            "Database error:",
            e
        )

        return False


    finally:

        conn.close()


# ============================================================
# DISCHARGE ERROR
# ============================================================

class DischargeError(Exception):

    pass


# ============================================================
# GET CURRENTLY ADMITTED PATIENTS
# ============================================================

def get_admitted_patients():

    conn = get_connection()

    try:

        cursor = conn.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                p.id,
                p.name,
                b.bed_id,
                b.bed_number,
                b.ward
            FROM beds b

            INNER JOIN patients p
                ON p.id = b.patient_id

            WHERE b.is_occupied = 1

            ORDER BY
                b.ward,
                b.bed_number
            """
        )

        return cursor.fetchall()

    finally:

        conn.close()


# ============================================================
# GET PATIENT CURRENT BED
# ============================================================

def get_patient_current_bed(
    patient_id
):

    conn = get_connection()

    try:

        cursor = conn.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                bed_id,
                ward,
                bed_number,
                bed_type,
                is_occupied,
                patient_id
            FROM beds

            WHERE patient_id = %s
              AND is_occupied = 1

            ORDER BY bed_id

            LIMIT 1
            """,
            (patient_id,)
        )

        return cursor.fetchone()

    finally:

        conn.close()


# ============================================================
# GET LATEST BED ASSIGNMENT
# ============================================================

def get_latest_assignment(
    patient_id,
    bed_id
):

    conn = get_connection()

    try:

        cursor = conn.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                assignment_id,
                nurse_assigned,
                assigned_at,
                assigned_by

            FROM bed_assignments

            WHERE patient_id = %s
              AND bed_id = %s

            ORDER BY
                assigned_at DESC,
                assignment_id DESC

            LIMIT 1
            """,
            (
                patient_id,
                bed_id
            )
        )

        return cursor.fetchone()

    finally:

        conn.close()


# ============================================================
# CREATE DISCHARGE RECORD
# ============================================================

def create_discharge_record(
    cursor,
    patient_id,
    bed,
    summary,
    reason,
    discharged_by,
    admitted_at,
    discharged_at
):

    cursor.execute(
        """
        INSERT INTO discharges
        (
            patient_id,
            bed_id,
            ward,
            bed_number,
            admitted_at,
            discharge_reason,
            discharge_summary,
            discharged_at,
            discharged_by
        )

        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        """,
        (
            patient_id,
            bed["bed_id"],
            bed["ward"],
            bed["bed_number"],
            admitted_at,
            reason,
            summary,
            discharged_at,
            discharged_by
        )
    )


    if cursor.rowcount != 1:

        raise DischargeError(
            "Discharge record insert failed."
        )


    return cursor.lastrowid


# ============================================================
# RELEASE BED
# ============================================================

def release_patient_bed(
    cursor,
    patient_id,
    bed_id
):

    cursor.execute(
        """
        UPDATE beds

        SET
            is_occupied = 0,
            patient_id = NULL

        WHERE bed_id = %s
          AND patient_id = %s
          AND is_occupied = 1
        """,
        (
            bed_id,
            patient_id
        )
    )


    if cursor.rowcount != 1:

        raise DischargeError(
            "Bed release failed."
        )


    # Verify bed is released

    cursor.execute(
        """
        SELECT
            bed_id,
            ward,
            bed_number,
            is_occupied,
            patient_id

        FROM beds

        WHERE bed_id = %s
        """,
        (bed_id,)
    )


    row = cursor.fetchone()


    if (
        not row
        or row["is_occupied"] != 0
        or row["patient_id"] is not None
    ):

        raise DischargeError(
            "Bed release verification failed."
        )


    return row


# ============================================================
# COMPLETE DISCHARGE TRANSACTION
# ============================================================

def discharge_patient_transaction(
    patient_id,
    bed_id,
    summary,
    reason,
    discharged_by,
    admitted_at,
    discharged_at
):

    conn = get_connection()

    try:

        # Start transaction

        conn.start_transaction()

        cursor = conn.cursor(
            dictionary=True
        )


        # ----------------------------------------------------
        # LOCK BED
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT
                bed_id,
                ward,
                bed_number,
                bed_type,
                is_occupied,
                patient_id

            FROM beds

            WHERE bed_id = %s

            FOR UPDATE
            """,
            (bed_id,)
        )


        bed = cursor.fetchone()


        # ----------------------------------------------------
        # VALIDATE BED
        # ----------------------------------------------------

        if (
            bed is None
            or bed["is_occupied"] != 1
            or bed["patient_id"] != patient_id
        ):

            conn.rollback()

            logger.info(
                "Patient %s is no longer in bed %s",
                patient_id,
                bed_id
            )

            return None


        # ----------------------------------------------------
        # SAVE DISCHARGE HISTORY
        # ----------------------------------------------------

        discharge_id = create_discharge_record(
            cursor,
            patient_id,
            bed,
            summary,
            reason,
            discharged_by,
            admitted_at,
            discharged_at
        )


        logger.info(
            "Discharge record %s created",
            discharge_id
        )


        # ----------------------------------------------------
        # RELEASE BED
        # ----------------------------------------------------

        released_bed = release_patient_bed(
            cursor,
            patient_id,
            bed_id
        )


        logger.info(
            "Bed %s released",
            released_bed["bed_number"]
        )


        # ----------------------------------------------------
        # COMMIT
        # ----------------------------------------------------

        conn.commit()


        logger.info(
            "Discharge transaction completed"
        )


        return {
            "discharge_id":
                discharge_id,

            "bed":
                released_bed
        }


    except Exception:

        try:

            conn.rollback()

        except Exception:

            pass


        logger.exception(
            "Discharge transaction failed"
        )

        raise


    finally:

        conn.close()