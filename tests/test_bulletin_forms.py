import unittest

from monitoramento.bulletin_forms import (
    BULLETIN_FIELDS,
    HISTOPATHOLOGY_CHOICES,
    TRM_TB_CHOICES,
    prepare_original_values,
    prepare_updated_values,
    validate_form_values,
)


class BulletinDictionaryTests(unittest.TestCase):
    def test_histopathology_and_trm_codes_match_confirmed_bulletin_labels(self) -> None:
        self.assertEqual(
            [(option.code, option.description) for option in HISTOPATHOLOGY_CHOICES],
            [
                ("1", "BAAR positivo"),
                ("2", "Sugestivo de TB"),
                ("3", "Não sugestivo de TB"),
                ("4", "Em andamento"),
                ("5", "Não realizado"),
            ],
        )
        self.assertEqual(
            [(option.code, option.description) for option in TRM_TB_CHOICES],
            [
                ("1", "Detectável sensível à rifampicina"),
                ("2", "Não detectável resistente à rifampicina"),
                ("3", "Não detectável"),
                ("4", "Inconclusivo"),
                ("5", "Não realizado"),
            ],
        )

    def test_categorical_values_are_validated_as_codes_and_stored_with_labels(self) -> None:
        validated = validate_form_values(
            "tuberculose",
            {"histopatologia": "4", "bac_1_mes": "4"},
        )
        self.assertEqual(validated, {"histopatologia": "4", "bac_1_mes": "4"})
        self.assertEqual(
            prepare_updated_values("tuberculose", validated),
            {
                "histopatologia": {"codigo": "4", "descricao": "Em andamento"},
                "bac_1_mes": {"codigo": "4", "descricao": "Não se aplica"},
            },
        )

    def test_import_preserves_original_value_and_attaches_code_description(self) -> None:
        prepared = prepare_original_values(
            {"histopatologia": "3", "campo_nao_catalogado": "original"}
        )
        self.assertEqual(
            prepared["histopatologia"],
            {
                "codigo": "3",
                "descricao": "Não sugestivo de TB",
                "valor_original": "3",
            },
        )
        self.assertEqual(prepared["campo_nao_catalogado"], "original")

    def test_hansen_codes_are_separate_and_integer_fields_have_no_upper_cap(self) -> None:
        fields = {field.key: field for field in BULLETIN_FIELDS["hanseniase"]}
        self.assertEqual(fields["classificacao_operacional"].choices[0].code, "1")
        self.assertEqual(
            fields["classificacao_operacional"].choices[0].description,
            "PB — Paucibacilar",
        )
        self.assertEqual(
            validate_form_values(
                "hanseniase",
                {"doses_supervisionadas": "1000000", "tipo_saida": ""},
            ),
            {"doses_supervisionadas": "1000000", "tipo_saida": ""},
        )

    def test_invalid_or_numeric_categorical_values_are_rejected(self) -> None:
        for value in ("0", "6", "1.0", "Positivo"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Código inválido"):
                    validate_form_values("tuberculose", {"bac_1_mes": value})


if __name__ == "__main__":
    unittest.main()
