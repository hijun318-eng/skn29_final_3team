"""Release discovery가 사용하는 DataHub GraphQL 문서를 parser와 분리해 보관한다."""

SEARCH_QUERY = """
query ReleaseDatasets($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    start count total
    searchResults { entity { urn type } }
  }
}
""".strip()

DATASET_QUERY = """
query ReleaseDataset($urn: String!) {
  dataset(urn: $urn) {
    urn name
    status { removed lifecycleStage { urn name description } }
    ownership {
      owners {
        owner {
          __typename
          ... on CorpGroup { urn name info { displayName description } }
          ... on CorpUser { urn username properties { displayName } }
        }
      }
    }
    domain { domain { urn properties { name description } } }
    properties { name qualifiedName description customProperties { key value } }
    schemaMetadata {
      version name platformUrn hash
      fields { fieldPath nativeDataType nullable isPartOfKey description }
    }
  }
}
""".strip()

TERM_QUERY = """
query ReleaseGlossaryTerm($urn: String!) {
  glossaryTerm(urn: $urn) {
    urn exists
    status { removed lifecycleStage { urn name description } }
    ownership {
      owners {
        owner {
          __typename
          ... on CorpGroup { urn name info { displayName description } }
          ... on CorpUser { urn username properties { displayName } }
        }
      }
    }
    domain { domain { urn properties { name description } } }
    glossaryTermInfo { name description customProperties { key value } }
  }
}
""".strip()

LIFECYCLE_QUERY = """
query ReleaseLifecycleStages {
  listLifecycleStages { urn name description }
}
""".strip()
