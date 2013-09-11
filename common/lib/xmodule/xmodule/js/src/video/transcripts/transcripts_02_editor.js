(function (window, undefined) {
    Transcripts.Editor = Backbone.View.extend({

        tagName: 'div',

        // TODO: JS test.
        initialize: function () {
            var metadata = this.$el.data('metadata'),
                models = this.toModels(metadata);

            this.collection = new CMS.Models.MetadataCollection(models);

            this.metadataEditor = new CMS.Views.Metadata.Editor({
                el: this.$el,
                collection: this.collection
            });
        },

        // Convert metadata JSON to List of models
        //
        // TODO: JS test.
        toModels: function (data) {
            var metadata = (_.isString(data)) ? JSON.parse(data) : data,
                models = [];

            for (var model in metadata) {
                if (metadata.hasOwnProperty(model)) {
                    models.push(metadata[model]);
                }
            }

            return models;
        },

        syncBasicTab: function (metadataCollection) {
            var result = [],
                utils = Transcripts.Utils,
                getField = utils.getField,
                html5SourcesValue, youtubeValue, videoUrl;

            if (!metadataCollection) {
                return false;
            }

            html5SourcesValue = getField(metadataCollection, 'html5_sources')
                                    .getDisplayValue();

            youtubeValue = getField(metadataCollection, 'youtube_id_1_0')
                                    .getDisplayValue();

            videoUrl = getField(this.collection, 'video_url');

            youtubeValue = (youtubeValue.length === 11)
                                ? utils.getYoutubeLink(youtubeValue)
                                : '';

            result.push(youtubeValue);
            result = result.concat(html5SourcesValue);

            videoUrl.setValue(result);
            utils.syncCollections(metadataCollection, this.collection);
        },

        syncAdvancedTab: function (metadataCollection) {
            var utils = Transcripts.Utils,
                getField = utils.getField,
                html5Sources, youtube, videoUrlValue, result;


            if (!metadataCollection) {
                return false;
            }

            html5Sources = getField(
                                metadataCollection,
                                'html5_sources'
                            );

            youtube = getField(
                                metadataCollection,
                                'youtube_id_1_0'
                            );

            videoUrlValue = getField(this.collection, 'video_url')
                                .getDisplayValue();

            result = _.groupBy(
                videoUrlValue,
                function (value) {
                    return utils.parseLink(value).mode;
                }
            );


            // TODO: CHECK result['html5']
            if (html5Sources) {
                html5Sources.setValue(result.html5 || []);
            }

            if (youtube) {
                result = (result.youtube)
                            ? utils.parseLink(result.youtube[0]).video
                            : '';

                youtube.setValue(result);
            }

            utils.syncCollections(this.collection, metadataCollection);
        }

    });
}(this));
